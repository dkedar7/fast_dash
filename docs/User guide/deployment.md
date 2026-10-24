# Deployment

Fast Dash apps are deployed as any other Flask app. A universal and hence the recommended way to deploy is to containerize the application and then deploy it to an endpoint.

Here're the general steps involved with the deployment process:

1. Extract the Flask server from the `FastDash` app object (`server = app.server`).
2. Add a `Dockerfile` in the same directory that contains the main Fast Dash app module.
3. Build and run Docker container.

## The quick way: `fastdash create`

Fast Dash installs a `fastdash` command that scaffolds a project ready to
deploy:

```bash
fastdash create my-app --port 8080     # 8080 for Google Cloud Run, 7860 for Hugging Face Spaces
cd my-app
```

It writes three files:

- `app.py`: your function, wrapped in `FastDash(...)`, with `server = app.server`
- `requirements.txt`: `fast-dash` and `gunicorn`
- `Dockerfile`: a Python 3.13 image that serves `app:server` with gunicorn

Replace the example function in `app.py` with yours, then deploy the folder as
described below. To build the same files by hand, follow the steps in the rest
of this page.

## By hand

The recommended directory structure is:

```
root\
- app.py
- requirements.txt
- Dockerfile
- ....py (Other scripts that your Fast Dash app needs)
- ... (Other dependencies)
```

With these steps in mind, let's see how we can deploy our simple text-to-text Fast Dash app to Google Cloud Run. We can use the same process to deploy to any service that deploys web applications as Docker containers, like Hugging Face spaces.

## 1. Google Cloud Run

### Step 0. Get started with Google Cloud

Get started with Google Cloud [here](https://cloud.google.com/). If you already have an account, proceed to the console and select Cloud Run from the list of services.

Although not mandatory, it's highly recommended to get access to the [`gcloud` command line utility](https://cloud.google.com/sdk/docs/install). The `gcloud` CLI reduces the lines of code need to deploy apps down to just one!

### Step 1. Extract Flask server object

Note that `@fastdash` decorators are not recommended for production deployment. So if you've been using the decorator to develop the app locally, use the `FastDash` class instead for production deployments. Then, simply define the server object with `app.server`.

```py
...
app = FastDash(callback_function, ...)
server = app.server
```

`server` is the Flask object that gets deployed. We need to isolate it so we can instruct `gunicorn` in the next step to deploy it inside our Docker container.

### Step 2. Create `Dockerfile`

Create a Dockerfile in the current path and modify it to reflect the following:

```
# Fast Dash needs Python 3.11 or newer
FROM python:3.13-slim

# Copy local code to the container image.
ADD . /app
WORKDIR /app

# Install production dependencies.
RUN pip3 install --no-cache-dir -r requirements.txt

# Serve the `server` object from app.py with gunicorn
CMD exec gunicorn app:server --bind :$PORT
```

`app:server` means "the `server` object in `app.py`". If your module has a
different name, change the part before the colon to match.

### Step 3. Update `requirements.txt`

List `fast-dash` and `gunicorn` in `requirements.txt`. Fast Dash requires
Python 3.11 or newer; on an older Python image, pip silently installs an old
release that lacks most of the features in these docs.

### Step 4. Deploy! 🚀

If the `gcloud` CLI was correctly installed in step 1, simply run this command from the root of your project directory:

```
gcloud run deploy
```

You will be asked to choose a few different settings for your deployment. Read Google Cloud Run's documentation here to understand what each of them mean.

That's it! Google Cloud will build your app inside a Docker container and display the URL once it's ready. The entire operation can take upto five minutes for simple applications. The build time highly depends on the complexity of your app and the number of dependencies.

## Deploying an app with `mcp_server=True`

Nothing extra is needed: `/mcp` is mounted when the app object is built, so `server = app.server` carries it and `gunicorn app:server` serves it alongside the UI. For `backend="fastapi"`, `app.server` is an ASGI app, so serve it with `uvicorn app:server --host 0.0.0.0 --port $PORT` instead (and add `uvicorn` to `requirements.txt`).

!!! warning
    `/mcp` has no authentication — anyone who can reach it can run your callback. Put it behind your own auth (a reverse proxy or your platform's access controls) before exposing a deployed app.