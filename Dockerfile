FROM opensuse/tumbleweed

# Install required system packages
RUN zypper -n in -y \
    python3 \
    python3-pip \
    git-core \
    ImageMagick \
    ghostscript \
    libpango-1_0-0 \
    libcairo2 \
    libgdk_pixbuf-2_0-0 \
    && zypper clean -a

# Remove ImageMagick restrictions on PDF
RUN sed -i '/pattern="PDF"/d' /etc/IM-*/policy.xml /etc/ImageMagick-*/policy.xml 2>/dev/null || true

# Set up working directory for the application
WORKDIR /app

# Copy requirement file first to leverage Docker cache
COPY requirements.txt /app/

# Install python dependencies
RUN pip install --break-system-packages -r requirements.txt

# Copy application files
COPY backlogger.py head.html foot.html entrypoint.sh queries.yaml /app/

# Set up entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
