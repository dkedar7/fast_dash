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

For an app that streams (`stream=True` or `chat=`), add `--backend fastapi`.
The scaffold then builds the app on the FastAPI backend, lists
`fast-dash[fastapi]` in `requirements.txt`, and serves `app:server` with
uvicorn, which streams in production (see
[Streaming and chat apps](#streaming-and-chat-apps)).

Replace the example function in `app.py` with yours, then deploy the folder as
described below. To build the same files by hand, follow the steps in the rest
of this page.

## If the page comes up blank: `fastdash doctor`

A page that loads with nothing on it, and no error in the server log, is
usually a version clash in the browser: `dash-mantine-components` 3 needs
React 19, but Dash serves React 18 unless told otherwise. Fast Dash warns about
this when it builds the app, and `fastdash doctor` checks the environment it
runs in:

```bash
fastdash doctor
```

It prints the installed `fast-dash`, `dash` and component-library versions,
the React version Dash serves, and the fix for any clash it knows about. It
exits with status 1 when it finds one, so you can run it in a container build.

For a `stream=True` app, `fastdash doctor --stream http://127.0.0.1:8080/`
checks that updates reach a client while the callback runs; see
[Streaming and chat apps](#streaming-and-chat-apps).

For an app built with `mcp_server=True`, `fastdash doctor --mcp
http://127.0.0.1:8080/mcp` checks the running app's agent surface the way an
MCP client sees it, and exits with status 1 if an agent couldn't drive it.
It needs `pip install mcp`. See
[Checking that MCP is up](ai_agents.md#connect-an-agent).

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

## Streaming and chat apps

Apps built with `stream=True` or `chat=` push each update to the browser
while the callback runs. On the default Flask backend that push goes over
socket.io, and gunicorn's default worker can't serve socket.io. Under a plain
`gunicorn app:server`, a streamed Run shows only its final output (the server
log warns once), and a chat turn answers with an error naming the fix.

To stream in production, build the app on the FastAPI backend and serve it
with uvicorn. It streams over a native WebSocket, with no socket.io involved:

```bash
pip install 'fast-dash[fastapi]'      # includes uvicorn
```

```py
app = FastDash(callback_fn=counter, stream=True, backend="fastapi")
server = app.server
```

```
CMD exec uvicorn app:server --host 0.0.0.0 --port $PORT
```

To stay on Flask, run gunicorn with a single eventlet or gevent worker, as
the [Flask-SocketIO deployment guide](https://flask-socketio.readthedocs.io/en/latest/deployment.html)
describes. `app.run()` uses a socket.io-aware server, which is why streaming
works locally either way.

To check that a running app really streams, point `fastdash doctor --stream`
at it. It connects the way the page does (socket.io on Flask, the WebSocket on
the FastAPI backend), presses Run once with the inputs' current values, and
counts the updates that arrive while the Run is still in flight:

```console
$ fastdash doctor --stream http://127.0.0.1:8080/
Connecting to http://127.0.0.1:8080/ ...
  transport        OK   socket.io (Flask backend), socket L-Tbua8nQS-tYtsyAAAF
  run              OK   Run returned HTTP 200 after 1.23s
  streaming        OK   3 updates arrived while the Run was in flight, 0.027s to 0.83s (tick 1
 / tick 1
tick 2
 / ...)
Streaming wire healthy.
```

It exits with status 1 and names the likely fix when only the final output
arrives, or when the Run never returns while the socket is open, as under a
single sync worker. `--json` prints every update with its timing. It runs your
function once, so point it at an app where that's safe. Chat apps (`chat=`)
aren't covered yet.

## Deploying an app with `mcp_server=True`

Nothing extra is needed: `/mcp` is mounted when the app object is built, so `server = app.server` carries it and `gunicorn app:server` serves it alongside the UI. For `backend="fastapi"`, `app.server` is an ASGI app, so serve it with `uvicorn app:server --host 0.0.0.0 --port $PORT` instead (and add `uvicorn` to `requirements.txt`).

!!! warning
    `/mcp` has no authentication — anyone who can reach it can run your callback. Put it behind your own auth (a reverse proxy or your platform's access controls) before exposing a deployed app.