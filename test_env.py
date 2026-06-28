# 用来一键读取.env所有配置，校验是否加载成功
import os
from dotenv import load_dotenv

# 加载环境变量，覆盖系统旧变量
load_dotenv(override=True)

if __name__ == "__main__":
    print("======模型缓存配置======")
    print(f"MINERU_MODEL_SOURCE: {os.getenv('MINERU_MODEL_SOURCE')}")
    print(f"MODELSCOPE_OFFLINE: {os.getenv('MODELSCOPE_OFFLINE')}")
    print(f"MODELSCOPE_CACHE: {os.getenv('MODELSCOPE_CACHE')}")
    print(f"HF_HOME: {os.getenv('HF_HOME')}")
    print(f"MD_ROOT_DIR: {os.getenv('MD_ROOT_DIR')}")

    print("\n======LLM接口配置======")
    print(f"OPENAI_API_BASE: {os.getenv('OPENAI_API_BASE')}")
    print(f"OPENAI_API_KEY: {os.getenv('OPENAI_API_KEY')[:15]}******")  # 只打印前半段，保护密钥
    print(f"LLM_DEFAULT_MODEL: {os.getenv('LLM_DEFAULT_MODEL')}")
    print(f"LLM_DEFAULT_TEMPERATURE: {os.getenv('LLM_DEFAULT_TEMPERATURE')}")
    print(f"VL_MODEL: {os.getenv('VL_MODEL')}")