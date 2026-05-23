# Development Container Setup

Nhà phát triển này đã được cấu hình để hoạt động với VS Code Remote - Containers hoặc Docker Desktop.

## Yêu cầu

- Docker Desktop (hoặc Docker Engine + Docker CLI)
- VS Code với extension "Dev Containers"
- 4GB+ RAM (khuyên nghị 8GB)

## Cách sử dụng

### Option 1: VS Code Remote - Containers (Khuyến khích)

1. Cài đặt extension "Dev Containers" trong VS Code
2. Mở project folder trong VS Code
3. Nhấn `Ctrl+Shift+P` (hoặc `Cmd+Shift+P` trên Mac)
4. Gõ "Dev Containers: Reopen in Container"
5. VS Code sẽ build image và mở project trong container

### Option 2: Docker Compose

```bash
# Build và start container
docker-compose -f .devcontainer/docker-compose.yml up -d

# Kết nối đến container
docker exec -it neuf-log-viewer-dev bash

# Stop container
docker-compose -f .devcontainer/docker-compose.yml down
```

## Các công cụ được cài đặt

- **Python 3.11** - Phiên bản Python chính
- **FastAPI** - Web framework
- **pytest** - Testing framework
- **black** - Code formatter
- **pylint** - Code linter
- **mypy** - Static type checker
- **VS Code Extensions**:
  - Python
  - Pylance
  - Debugpy
  - Black Formatter
  - Ruff

## Ports

- **8000**: FastAPI Development Server
- **3000**: Frontend Development Server

## Các lệnh thường dùng

```bash
# Cài đặt dependencies
pip install -r requirements.txt

# Chạy API server
python -m uvicorn neuf_log_viewer_api:app --reload

# Chạy tests
pytest test/

# Format code với Black
black src/ test/ *.py

# Lint với Pylint
pylint src/ test/ *.py

# Type checking
mypy src/ test/ *.py
```

## Environment Variables

Có thể tùy chỉnh môi trường bằng cách thêm file `.env`:

```bash
# .env
PYTHONUNBUFFERED=1
PYTHONDONTWRITEBYTECODE=1
```

## Troubleshooting

### Container không build được

```bash
# Xóa cache và rebuild
docker system prune -a
docker-compose -f .devcontainer/docker-compose.yml build --no-cache
```

### Permission denied errors

```bash
# Chạy với sudo (nếu cần)
sudo docker-compose -f .devcontainer/docker-compose.yml up
```

### Port đã được sử dụng

```bash
# Kiểm tra process đang dùng port
netstat -ano | findstr :8000

# Dừng process hoặc thay đổi port trong docker-compose.yml
```

## Tài liệu tham khảo

- [VS Code Dev Containers](https://code.visualstudio.com/docs/devcontainers/containers)
- [Docker Documentation](https://docs.docker.com/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

