# IntelliJ Setup cho Devcontainer

Hướng dẫn cấu hình IntelliJ IDEA để phát triển với devcontainer được tạo sẵn.

## Yêu cầu

- IntelliJ IDEA (Community hoặc Professional Edition)
- Docker Desktop cài đặt và chạy
- Plugin "Docker" (thường đã cài sẵn)

## Cách 1: Sử dụng Docker Compose Configuration (Khuyến khích)

### Bước 1: Mở Services Window
1. Vào **View** → **Tool Windows** → **Services** (hoặc `Alt+8`)
2. Nhấp vào nút **+** để thêm service

### Bước 2: Cấu hình Docker Compose
1. Chọn **Docker Compose**
2. Chỉ định file: `.devcontainer/docker-compose.yml`
3. Nhấp **Apply**

### Bước 3: Build và Start Container
1. Trong **Services** window, nhấp chuột phải trên service
2. Chọn **Build**
3. Sau đó chọn **Run container**
4. Container sẽ khởi động tại `neuf-log-viewer-dev`

## Cách 2: Cấu hình Python Interpreter từ Docker

### Bước 1: Mở Project Settings
1. Vào **File** → **Settings** (hoặc `Ctrl+Alt+S`)
2. Tìm **Project: [ProjectName]** → **Python Interpreter**

### Bước 2: Thêm Remote Interpreter
1. Nhấp biểu tượng **gear** (⚙)
2. Chọn **Add...**
3. Chọn **Docker Compose**

### Bước 3: Cấu hình Docker Compose
- **Configuration files**: `.devcontainer/docker-compose.yml`
- **Service**: `dev`
- Nhấp **OK** để hoàn thành

### Bước 4: Xác nhận
- Kiểm tra Python interpreter path hiển thị đúng
- IntelliJ sẽ download packages từ container

## Cháy 3: Debug và Run Configurations

### Chạy FastAPI Server
Run Configurations đã được tạo:
1. Mở **Run** menu
2. Chọn **Edit Configurations...**
3. Bạn sẽ thấy:
   - **FastAPI Server** - Chạy ứng dụng API
   - **Pytest Tests** - Chạy test suite

### Cách sử dụng:
1. Chọn configuration từ dropdown
2. Nhấp **Run** (⏵) hoặc nhấn `Shift+F10`
3. Output sẽ hiển thị trong **Run** window

## Các tính năng hữu ích

### Code Intelligence (Intellisense)
- Khi sử dụng interpreter từ container, IntelliJ sẽ:
  - Cung cấp auto-complete
  - Kiểm tra type errors
  - Gợi ý documentation
  - Hỗ trợ refactoring

### Debug
1. Đặt breakpoint bằng cách nhấp tại line number
2. Chạy configuration với mode **Debug** (🐛)
3. Sử dụng **Debug** window để kiểm tra variables

### Terminal trong IntelliJ
1. Mở **Terminal** window (`Alt+F12`)
2. Terminal sẽ chạy trên host machine
3. Để truy cập container:
   ```bash
   docker exec -it neuf-log-viewer-dev bash
   ```

## Các Lệnh Thực Dụng

Trong Terminal hoặc bằng cách nhấp chuột phải trong project:

```bash
# Cài dependencies
docker exec neuf-log-viewer-dev pip install -r requirements.txt

# Chạy tests
docker exec neuf-log-viewer-dev pytest test/ -v

# Format code
docker exec neuf-log-viewer-dev black src/ test/ *.py

# Type checking
docker exec neuf-log-viewer-dev mypy src/

# Lint code
docker exec neuf-log-viewer-dev pylint src/ test/ *.py
```

## Troubleshooting

### Python Interpreter không được nhận diện
```bash
# Rebuild container
docker-compose -f .devcontainer/docker-compose.yml build --no-cache
```

### Packages không được import
1. Chắc chắn dependencies được cài:
   ```bash
   docker exec neuf-log-viewer-dev pip install -r requirements.txt
   ```
2. Reload IntelliJ: **File** → **Invalidate Caches / Restart**

### Port 8000 đã được sử dụng
Trong `.devcontainer/docker-compose.yml`, thay đổi port mapping:
```yaml
ports:
  - "8001:8000"  # Thay 8001 thành port khác nếu cần
```

### Docker daemon không chạy
Mở Docker Desktop nếu dùng Windows/Mac hoặc:
```bash
sudo systemctl start docker  # Linux
```

## Tư vấn bổ sung

- **Plugins hữu ích**:
  - Python (IntelliJ)
  - BashSupport Pro
  - Docker
  - Makefile Language
  
- **Editor Settings**:
  - Vào **Settings** → **Editor** → **Code Style** → **Python**
  - Cấu hình indent, line length, v.v.

- **Project Structure**:
  - Vào **File** → **Project Structure**
  - Kiểm tra các SDK, libraries, excludes folders (ví dụ: `venv/`, `__pycache__/`)

Bây giờ bạn đã sẵn sàng phát triển với IntelliJ + Devcontainer! 🎉

