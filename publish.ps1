# 获取当前日期和时间，格式化为 YYYYMMDDHHMM
$tag = Get-Date -Format "yyyyMMdd-HHmm"

# 构建Docker镜像
docker build -f Dockerfile -t aaa . --progress=plain

# 打标签，包括基于时间的tag和latest tag
docker tag aaa registry.cn-shanghai.aliyuncs.com/xiaoin/playwright-fastapi:$tag
docker tag aaa registry.cn-shanghai.aliyuncs.com/xiaoin/playwright-fastapi:latest

# 推送镜像
docker push registry.cn-shanghai.aliyuncs.com/xiaoin/playwright-fastapi:$tag
docker push registry.cn-shanghai.aliyuncs.com/xiaoin/playwright-fastapi:latest
Write-Host "docker build tag : $tag, success!"