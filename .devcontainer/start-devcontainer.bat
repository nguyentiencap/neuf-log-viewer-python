@echo off
REM Quick DevContainer Start Script for Windows

echo Starting NEUF Log Viewer DevContainer...
echo.

REM Check if Docker is installed
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Docker is not installed or not in PATH
    echo Please install Docker Desktop from https://www.docker.com/products/docker-desktop
    pause
    exit /b 1
)

REM Check if docker-compose is available
docker-compose --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Docker Compose is not available
    echo Please ensure Docker Desktop is installed and running
    pause
    exit /b 1
)

REM Build and start container
echo Building and starting container...
docker-compose -f .devcontainer/docker-compose.yml up -d

if %errorlevel% neq 0 (
    echo Error: Failed to start container
    pause
    exit /b 1
)

echo.
echo Container started successfully!
echo.
echo Container name: neuf-log-viewer-dev
echo.
echo To access the container, run:
echo   docker exec -it neuf-log-viewer-dev bash
echo.
echo To view logs:
echo   docker-compose -f .devcontainer/docker-compose.yml logs -f
echo.
echo To stop the container:
echo   docker-compose -f .devcontainer/docker-compose.yml down
echo.

pause

