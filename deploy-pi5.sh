#!/bin/bash
#
# AI-SOC-v1 Deployment Script for Raspberry Pi 5
# Optimized for ARM64 architecture (Debian/Raspberry Pi OS)
#
# Usage: sudo ./deploy-pi5.sh
#
# Prerequisites:
#   - Raspberry Pi 5 (4GB or 8GB RAM recommended)
#   - Raspberry Pi OS (64-bit) or Debian 12+ ARM64
#   - Internet connection
#   - Sudo privileges
#

set -euo pipefail

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running on Raspberry Pi 5
check_platform() {
    log_info "Checking platform compatibility..."

    # Check architecture
    if [ "$(uname -m)" != "aarch64" ] && [ "$(uname -m)" != "arm64" ]; then
        log_error "This script requires ARM64 architecture. Detected: $(uname -m)"
        exit 1
    fi

    # Check for Raspberry Pi (best effort)
    if [ -f /proc/device-tree/model ]; then
        MODEL=$(cat /proc/device-tree/model)
        log_info "Detected: $MODEL"
        if [[ ! "$MODEL" =~ "Raspberry Pi" ]]; then
            log_warn "Not running on Raspberry Pi hardware. Proceeding anyway..."
        fi
    fi

    # Check RAM (recommend 4GB minimum)
    TOTAL_RAM=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
    RAM_GB=$((TOTAL_RAM / 1024 / 1024))
    log_info "Total RAM: ${RAM_GB}GB"

    if [ "$RAM_GB" -lt 4 ]; then
        log_warn "Less than 4GB RAM detected. AI-SOC may run slowly."
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

# Update system packages
update_system() {
    log_info "Updating system packages..."
    sudo apt-get update
    sudo apt-get upgrade -y
    sudo apt-get install -y \
        build-essential \
        git \
        curl \
        wget \
        ca-certificates \
        gnupg \
        lsb-release \
        python3-dev \
        python3-pip \
        python3-venv \
        libssl-dev \
        libffi-dev \
        libbz2-dev \
        libreadline-dev \
        libsqlite3-dev \
        zlib1g-dev
}

# Install Python 3.11+ if needed
install_python() {
    log_info "Checking Python version..."

    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version | awk '{print $2}')
        PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
        PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

        log_info "Detected Python $PYTHON_VERSION"

        if [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -ge 11 ]; then
            log_info "Python 3.11+ already installed ✓"
            return
        fi
    fi

    log_warn "Python 3.11+ required. Installing from source..."

    # Download and build Python 3.11
    cd /tmp
    wget https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tar.xz
    tar -xf Python-3.11.9.tar.xz
    cd Python-3.11.9

    ./configure --enable-optimizations --enable-shared LDFLAGS="-Wl,-rpath /usr/local/lib"
    make -j$(nproc)
    sudo make altinstall

    # Create symlinks
    sudo ln -sf /usr/local/bin/python3.11 /usr/local/bin/python3
    sudo ln -sf /usr/local/bin/pip3.11 /usr/local/bin/pip3

    log_info "Python 3.11 installed ✓"
}

# Install Poetry
install_poetry() {
    log_info "Installing Poetry..."

    if command -v poetry &> /dev/null; then
        log_info "Poetry already installed ✓"
        return
    fi

    curl -sSL https://install.python-poetry.org | python3 -

    # Add to PATH
    export PATH="$HOME/.local/bin:$PATH"
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

    log_info "Poetry installed ✓"
}

# Install Node.js (ARM64 optimized)
install_nodejs() {
    log_info "Installing Node.js for ARM64..."

    if command -v node &> /dev/null; then
        NODE_VERSION=$(node --version)
        log_info "Node.js $NODE_VERSION already installed ✓"
        return
    fi

    # Install NodeSource repository for ARM64
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs

    log_info "Node.js $(node --version) installed ✓"
}

# Install Docker (optional for LLM containers)
install_docker() {
    log_info "Installing Docker..."

    if command -v docker &> /dev/null; then
        log_info "Docker already installed ✓"
        return
    fi

    # Add Docker's official GPG key
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    # Add repository
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Add current user to docker group
    sudo usermod -aG docker $USER

    log_info "Docker installed ✓"
    log_warn "Please log out and back in for Docker group membership to take effect"
}

# Install Kafka (lightweight setup for Pi)
install_kafka() {
    log_info "Setting up Kafka for Raspberry Pi..."

    # Use Docker Compose for easier management
    cat > /tmp/kafka-docker-compose.yml <<'EOF'
version: '3.8'

services:
  zookeeper:
    image: arm64v8/zookeeper:3.8
    container_name: zookeeper
    ports:
      - "2181:2181"
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000
    restart: unless-stopped

  kafka:
    image: confluentinc/cp-kafka:7.5.0
    container_name: kafka
    depends_on:
      - zookeeper
    ports:
      - "9092:9092"
      - "9093:9093"
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092,EXTERNAL://localhost:9093
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,EXTERNAL:PLAINTEXT
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"
      KAFKA_LOG_RETENTION_HOURS: 24
      KAFKA_LOG_SEGMENT_BYTES: 104857600
    restart: unless-stopped
    mem_limit: 1g
    mem_reservation: 512m

  redis:
    image: arm64v8/redis:7-alpine
    container_name: redis
    ports:
      - "6379:6379"
    restart: unless-stopped
    mem_limit: 512m
EOF

    sudo mv /tmp/kafka-docker-compose.yml /opt/ai-soc/kafka-docker-compose.yml
    log_info "Kafka configuration created at /opt/ai-soc/kafka-docker-compose.yml"
}

# Install AI-SOC backend
install_backend() {
    log_info "Installing AI-SOC FastAPI backend..."

    cd /opt/ai-soc/ai_soc

    # Install dependencies with Poetry
    poetry install --no-dev

    log_info "Backend dependencies installed ✓"
}

# Install AI-SOC frontend
install_frontend() {
    log_info "Installing AI-SOC React frontend..."

    cd /opt/ai-soc

    # Install npm dependencies
    npm install

    # Build for production
    npm run build

    log_info "Frontend built ✓"
}

# Create systemd services
create_systemd_services() {
    log_info "Creating systemd services..."

    # Backend service
    cat > /tmp/ai-soc-backend.service <<EOF
[Unit]
Description=AI-SOC FastAPI Backend
After=network.target kafka.service redis.service

[Service]
Type=simple
User=$USER
WorkingDirectory=/opt/ai-soc/ai_soc
Environment="PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
Environment="AI_SOC_KAFKA_BOOTSTRAP_SERVERS=localhost:9092"
ExecStart=/usr/local/bin/poetry run uvicorn ai_soc.main:app --host 0.0.0.0 --port 9000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    # Frontend service (using Python http.server for simplicity)
    cat > /tmp/ai-soc-frontend.service <<EOF
[Unit]
Description=AI-SOC React Frontend
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/opt/ai-soc/dist
ExecStart=/usr/bin/python3 -m http.server 5173
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    sudo mv /tmp/ai-soc-backend.service /etc/systemd/system/
    sudo mv /tmp/ai-soc-frontend.service /etc/systemd/system/

    sudo systemctl daemon-reload

    log_info "Systemd services created ✓"
}

# Configure environment
configure_environment() {
    log_info "Configuring environment..."

    # Create .env file template
    cat > /opt/ai-soc/.env.template <<'EOF'
# AI-SOC Configuration for Raspberry Pi 5

# Kafka Configuration
AI_SOC_KAFKA_BOOTSTRAP_SERVERS=localhost:9092
AI_SOC_KAFKA_GROUP_ID=ai-soc

# Topics
AI_SOC_TELEMETRY_TOPICS=rbp.metrics,rbp.proposals,rbp.approvals
AI_SOC_ALERTS_TOPIC=rbp.alerts
AI_SOC_QUOTA_UPDATES_TOPIC=rbp.quota_updates

# Threat Intelligence Feeds
AI_SOC_THREAT_INTEL_FEEDS=https://feeds.cve.org/,https://otx.alienvault.com/api/v1/indicators

# LLM Configuration
AI_SOC_LLM_MODEL=lumo-ai-soc
# AI_SOC_LLM_ENDPOINT=http://localhost:8081

# Review Board
# AI_SOC_REVIEW_BOARD_WEBHOOK=http://localhost:8080/webhook

# MinIO/S3 Configuration (for evidence storage)
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_SECURE=false

# Vault Configuration
VAULT_ADDR=http://localhost:8200
# VAULT_TOKEN=your-vault-token
EOF

    if [ ! -f /opt/ai-soc/.env ]; then
        cp /opt/ai-soc/.env.template /opt/ai-soc/.env
        log_info "Created .env file from template"
    else
        log_warn ".env file already exists, not overwriting"
    fi
}

# Optimize for Raspberry Pi
optimize_for_pi() {
    log_info "Applying Raspberry Pi optimizations..."

    # Increase swap for 4GB models
    CURRENT_SWAP=$(free -m | awk '/^Swap:/ {print $2}')
    if [ "$CURRENT_SWAP" -lt 2048 ]; then
        log_info "Increasing swap to 2GB..."
        sudo dphys-swapfile swapoff || true
        sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
        sudo dphys-swapfile setup
        sudo dphys-swapfile swapon
    fi

    # Set CPU governor to performance (optional)
    log_info "Setting CPU governor to performance mode..."
    echo "performance" | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor >/dev/null || true

    log_info "Pi optimizations applied ✓"
}

# Main installation flow
main() {
    log_info "Starting AI-SOC deployment on Raspberry Pi 5..."
    echo ""

    # Check prerequisites
    if [ "$EUID" -eq 0 ]; then
        log_error "Do not run this script as root. Use: ./deploy-pi5.sh"
        exit 1
    fi

    # Create installation directory
    sudo mkdir -p /opt/ai-soc
    sudo chown $USER:$USER /opt/ai-soc

    # Copy repository to /opt/ai-soc if not already there
    if [ "$(pwd)" != "/opt/ai-soc" ]; then
        log_info "Copying repository to /opt/ai-soc..."
        cp -r "$(dirname "$0")"/* /opt/ai-soc/
    fi

    # Run installation steps
    check_platform
    update_system
    install_python
    install_poetry
    install_nodejs

    read -p "Install Docker for LLM containers? (Y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        install_docker
        install_kafka
    fi

    install_backend
    install_frontend
    create_systemd_services
    configure_environment
    optimize_for_pi

    echo ""
    log_info "═══════════════════════════════════════════════════════════"
    log_info "  AI-SOC Deployment Complete!"
    log_info "═══════════════════════════════════════════════════════════"
    echo ""
    log_info "Next steps:"
    echo ""
    echo "  1. Edit configuration:"
    echo "     nano /opt/ai-soc/.env"
    echo ""
    echo "  2. Start Kafka and Redis (if using Docker):"
    echo "     cd /opt/ai-soc && docker compose -f kafka-docker-compose.yml up -d"
    echo ""
    echo "  3. Start AI-SOC services:"
    echo "     sudo systemctl enable ai-soc-backend"
    echo "     sudo systemctl start ai-soc-backend"
    echo "     sudo systemctl enable ai-soc-frontend"
    echo "     sudo systemctl start ai-soc-frontend"
    echo ""
    echo "  4. Check service status:"
    echo "     sudo systemctl status ai-soc-backend"
    echo "     sudo systemctl status ai-soc-frontend"
    echo ""
    echo "  5. Access the dashboard:"
    echo "     http://$(hostname -I | awk '{print $1}'):5173"
    echo ""
    echo "  6. Backend API:"
    echo "     http://$(hostname -I | awk '{print $1}'):9000/docs"
    echo ""
    log_info "═══════════════════════════════════════════════════════════"
    echo ""
    log_warn "SECURITY REMINDER: Update default credentials in .env before production use!"
    echo ""
}

# Run main function
main "$@"
