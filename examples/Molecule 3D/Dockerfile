FROM continuumio/miniconda3

# Copy local code to the container image.
ADD . /app
WORKDIR /app

# Install production dependencies.
RUN conda env create -f environment.yml

# Make RUN commands use the new environment:
SHELL ["conda", "run", "-n", "molecule-3d-env", "/bin/bash", "-c"]

# Deploy app using gunicorn
CMD exec gunicorn wsgi:server --bind :$PORT