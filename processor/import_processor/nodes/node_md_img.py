# processor/import_processor/nodes/node_md_img.py
import base64
import json
import logging
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Tuple, List, Deque, Dict, Optional

from langchain_openai import ChatOpenAI
from minio import Minio

from processor.import_processor.base import BaseNode, setup_logging
from processor.import_processor.exceptions import StateFieldError, FileProcessingError
from processor.import_processor.state import ImportGraphState
from utils.minio_utils import get_minio_client, clean_minio_dir, upload_to_minio


class NodeMDImg(BaseNode):
    """
    MarkDown图片处理节点：多模态图片理解
    """

    name = "node_md_img"

    def process(self, state: ImportGraphState):
        """
        MD文件图片处理核心节点
        核心流程：
        1. 获取MD内容、文件路径、图片文件夹路径
        2. 扫描图片文件夹，筛选MD中实际引用的支持格式图片
        3. 调用多模态大模型为图片生成内容摘要
        4. 将图片上传至MinIO，替换MD中本地图片路径为MinIO访问URL，并填充图片摘要
        5. 备份原MD文件，保存处理后的新MD文件并更新状态

        :param state: md_path、md_content
        :return: md_path、md_content
        """

        md_content, md_path_obj, images_dir = self._step_1_get_content(state)
        if not images_dir.exists():
            self.logger.info("无图片文件夹，跳过图片处理")
            return state

        target_images = self._step_2_scan_images(md_content, images_dir)
        if not target_images:
            self.logger.info("未检测到MD中引用了图片，跳过图片处理")
            return state

        summaries = self._step_3_generate_summaries(md_path_obj.stem, target_images)

        new_md_content = self._step_4_upload_and_replace(md_path_obj.stem, target_images, summaries, md_content)

        new_md_file_name = self._step_5_backup_new_md_file(state['md_path'], new_md_content)

        state["md_content"] = new_md_content
        state["md_path"] = new_md_file_name

        return state

    def _step_5_backup_new_md_file(self, origin_md_path: str, md_content: str) -> str:
        """
        步骤5：将处理后的MD内容保存为新文件
        """
        new_md_file_name = os.path.splitext(origin_md_path)[0] + "_new.md"
        with open(new_md_file_name, "w", encoding="utf-8") as f:
            f.write(md_content)
        return new_md_file_name

    def _step_4_upload_and_replace(
            self,
            doc_stem: str,
            target_images: List[Tuple[str, str, Tuple[str, str]]],
            summaries: Dict[str, str],
            md_content: str
    ) -> str:
        """
        步骤 4: 上传图片并合并信息，然后替换 Markdown 中的内容。
        """
        minio_client = get_minio_client()
        if not minio_client:
            self.logger.error("MinIO客户端未初始化，跳过图片上传")
            return md_content

        minio_dir = self.config.minio_img_dir
        upload_dir = f"{minio_dir}/{doc_stem}".replace(" ", "")

        clean_minio_dir(minio_client, upload_dir)

        urls = self._upload_images_batch(minio_client, upload_dir, target_images)

        image_info = self._merge_summary_and_url(summaries, urls)

        md_content = self._process_md_file(md_content, image_info)

        return md_content

    def _process_md_file(self, md_content: str, image_info: Dict[str, Tuple[str, str]]) -> str:
        """
        核心功能：替换MD内容中的本地图片引用为MinIO远程引用
        """
        for image_file, (summary, new_url) in image_info.items():
            pattern = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_file) + r".*?\)")
            md_content = pattern.sub(lambda m: f"![{summary}]({new_url})", md_content)
        return md_content

    def _merge_summary_and_url(self, summaries: Dict[str, str], urls: Dict[str, str]) -> Dict[str, Tuple[str, str]]:
        """
        合并图片摘要字典和URL字典，过滤掉上传失败无URL的图片
        """
        image_info = {}
        for image_file, summary in summaries.items():
            if url := urls.get(image_file):
                image_info[image_file] = (summary, url)
        return image_info

    def _upload_images_batch(self, minio_client: Minio, upload_dir: str, target_images: List[Tuple]) -> Dict[str, str]:
        """
        批量上传待处理图片至MinIO，返回图片文件名与访问URL的映射关系
        """
        urls = {}
        for img_file, img_path, _ in target_images:
            object_name = f"{upload_dir}/{img_file}"
            url = upload_to_minio(minio_client, img_path, object_name)
            if url:
                urls[img_file] = url
            else:
                self.logger.warning(f"图片上传失败，跳过替换: {img_file}")
        return urls

    def _step_3_generate_summaries(self, doc_stem: str, target_images: List[Tuple[str, str, Tuple[str, str]]]) -> Dict[str, str]:
        """
        步骤3：批量为待处理图片生成内容摘要，带API速率限制
        """
        summaries = {}
        request_deque = deque()

        for img_file, img_path, context in target_images:
            self._apply_api_rate_limit(request_deque, 10)
            summaries[img_file] = self._summarize_image(img_path, root_folder=doc_stem, image_content=context)

        return summaries

    def _summarize_image(self, image_path: str, root_folder: str, image_content: Tuple[str, str]) -> str:
        """
        调用多模态大模型总结图片内容。
        """
        with open(image_path, "rb") as f:
            base64_image = base64.b64encode(f.read()).decode("utf-8")

        try:
            chat_model = ChatOpenAI(
                model=self.config.vl_model,
                api_key=self.config.openai_api_key,
                base_url=self.config.openai_api_base,
                temperature=self.config.llm_temperature
            )

            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"""这是"{root_folder}"文件中的一张图片，图片上文部分为"{image_content[0]}"，下文部分为"{image_content[1]}"，请用中文简要总结这张图片的内容，用于 Markdown 图片标题。"""
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ]

            response = chat_model.invoke(messages)
            return response.content.strip().replace("\n", "")

        except Exception as e:
            self.logger.error(f"获取图片摘要失败:{image_path}， 错误：{e}")
            return root_folder

    def _apply_api_rate_limit(
            self,
            request_times: Deque[float],
            max_requests: int,
            window_seconds: int = 60
    ) -> None:
        """
        通用滑动窗口API速率限制器
        """
        current_time = time.time()

        while request_times and current_time - request_times[0] >= window_seconds:
            request_times.popleft()

        if len(request_times) >= max_requests:
            sleep_duration = window_seconds - (current_time - request_times[0])
            if sleep_duration > 0:
                self.logger.info(f"请求被限速，等待{sleep_duration:.2f}秒...")
                time.sleep(sleep_duration)
                current_time = time.time()
                while request_times and current_time - request_times[0] >= window_seconds:
                    request_times.popleft()

        request_times.append(current_time)
        self.logger.info(f"{self.name} 请求成功，当前{window_seconds}s窗口内请求次数为{len(request_times)}")

    def _step_2_scan_images(self, md_content: str, images_dir: Path) -> List[Tuple[str, str, Tuple[str, str]]]:
        """
        扫描图片文件夹，过滤出「支持格式+MD中实际引用」的图片
        """
        target_images = []
        for image_file in os.listdir(images_dir):
            file_ext = os.path.splitext(image_file)[1].lower()
            if file_ext not in self.config.image_extensions:
                self.logger.warning(f"图片{image_file}格式不支持")
                continue

            img_path = str(images_dir / image_file)

            context = self._find_image_in_md(md_content, image_file)
            if not context:
                self.logger.warning(f"图片{image_file}未在md文档中找到")
                continue

            target_images.append((image_file, img_path, context))

        return target_images

    def _step_1_get_content(self, state: ImportGraphState) -> Tuple[str, Path, Path]:
        """
        从全局状态中提取并初始化MD处理所需核心数据
        """
        md_path = state.get("md_path")
        if not md_path:
            raise StateFieldError(
                field_name="md_path",
                message="MD文件路径不能为空",
                expected_type=str)

        md_path_obj = Path(md_path)

        if not md_path_obj.exists():
            raise FileProcessingError(message=f"文件{md_path_obj.name}不存在")

        md_content = md_path_obj.read_text(encoding="utf-8")

        img_dir = md_path_obj.parent / "images"

        return md_content, md_path_obj, img_dir

    def _find_image_in_md(
            self,
            md_content: str,
            image_file: str,
            context_len: int = 100
    ) -> Optional[Tuple[str, str]]:
        """
        在MD内容中查找图片引用并返回上下文
        """
        pattern = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_file) + r".*?\)")
        match = pattern.search(md_content)
        if not match:
            return None

        start, end = match.span()
        pre_text = md_content[max(0, start - context_len):start]
        post_text = md_content[end:min(len(md_content), end + context_len)]

        return pre_text, post_text


if __name__ == "__main__":
    setup_logging()

    md_path = r"D:\output\hak180产品安全手册\hak180产品安全手册.md"
    if os.path.exists(md_path):
        with open(md_path, "r", encoding="utf-8") as f:
            md_content = f.read()
    else:
        md_content = ""
        md_path = ""

    init_state = {
        "md_path": md_path,
        "md_content": md_content
    }

    node_md_img = NodeMDImg()
    result = node_md_img(init_state)

    logging.getLogger().info(json.dumps(result, ensure_ascii=False, indent=4))
