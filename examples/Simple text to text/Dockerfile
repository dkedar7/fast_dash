FROM python:3.9-slim

# Copy local code to the container image.
ADD . /app
WORKDIR /app

# Install production dependencies.
RUN pip3 install --no-cache-dir -r requirements.txt

# Deploy app using gunicorn
CMD exec gunicorn wsgi:server --bind :$PORT