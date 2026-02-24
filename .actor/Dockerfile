FROM apify/actor-python:3.12

# Copy dependency files first for Docker layer caching
COPY requirements.txt ./

# Install Python dependencies
RUN echo "Python version:" \
    && python --version \
    && pip install --no-cache-dir -r requirements.txt \
    && echo "All packages installed successfully"

# Copy the entire project (Scweet library + src/ actor entrypoint)
COPY . ./

CMD ["python3", "-m", "src"]
