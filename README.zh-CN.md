# release-slotcheck

把承诺发布的系统/架构附件写成明确契约，检查每个附件是否恰好出现一次。
可同时要求 .sha256 / .sig 等配套文件，并检查非空、大小范围、重复、额外文件和 GitHub 上传状态。

Python 3.11+，运行时无第三方依赖，完全离线，不读取附件内容，不执行二进制文件。

~~~powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install .
.venv/Scripts/release-slotcheck.exe contract.json --release v1.2.3 --directory stage --json
python examples/demo.py
~~~

配置示例见 [examples/contract.json](examples/contract.json)。
matrix 展开目标组合，exclude 明确排除不支持的平台，companions 为每个文件添加配套后缀。
默认拒绝额外文件。版本占位符使用 --release 的原始值，不自动移除 v。

已有 GitHub 发布可将完整 API 响应保存成 UTF-8 JSON 后检查：

~~~sh
release-slotcheck contract.json --release v1.2.3 --github-json release.json --json
~~~

程序不调用 gh、不联网、不读取凭据。Windows PowerShell 5.1 默认重定向为 UTF-16，
请改用 Set-Content -Encoding UTF8 保存 API 输出。API 错误对象会报输入错误，
不会伪装成附件缺失。

退出码 0：检查通过；1：存在附件问题；2：输入无效、不可读或扫描不完整。
展示上限只限制样本，不改变完整计数和失败状态。

范围：检查附件名字、数量和大小，不能证明二进制架构正确，不能验证签名或校验和，
不能保证保存的 API 数据仍然最新。stage 必须是扁平目录，子目录、符号链接及重解析点
会被拒绝。请继续保留真实平台运行测试和内容哈希验证。

示例使用真实临时文件，先验证完整目录，再删除 arm64 附件确认失败，最后验证合成
GitHub JSON；运行后清理临时文件。卸载使用虚拟环境的
python -m pip uninstall release-slotcheck；工具无缓存或后台服务。
详细规则见 [英文文档](README.md)。

