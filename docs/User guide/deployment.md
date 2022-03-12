# Deployment

Fast Dash apps can be deployed as regular Dash apps. A universal and hence the preferred method to deploy is to containers the applications and then deploy to a public cloud endpoint.

Here're the general steps involved with the deployment process:

1. Add a `Dockerfile` in the same directory that contains the main Fast Dash app module.
2. Create `wsgi.py` Python script in the same path.
3. Build and run Docker container.

The recommended directory structure is this:

```
root\
- app.py
- requirements.txt
- ....py  # (Other scripts that your Fast Dash app needs)
```

With these steps in mind, let's see how we can deploy our simple text-to-text Fast Dash app to the most used cloud services.

## 1. Google Cloud Run

### Step 1. Get started with Google Cloud

Get started with Google Cloud [here](https://cloud.google.com/). If you already have an account, proceed to the console and select Cloud Run from the list of services.

Although not mandatory, it's highly recommended to get access to the [`gcloud` command line utility](https://cloud.google.com/sdk/docs/install). The `gcloud` CLI reduces the deployment down to just a single line of code.

### Step 2. Add `wsgi.py`

Add `wsgi.py` Python script to the current directory. Modify it and add the following lines:

```python
from app import app
server = app.app.server
```

`server` is the Flask object that gets deployed. We need to isolate it from the rest of the app code so that we can instruct `gunicorn` in the next step to deploy it inside our Docker container.

### Step 3. Create `Dockerfile`

Create a new file in the current path and modify it to reflect the following:

```
FROM python:3.9-slim

# Copy local code to the container image.
ADD . /app
WORKDIR /app

# Install production dependencies.
RUN pip3 install --no-cache-dir -r requirements.txt

# Deploy app using gunicorn
CMD exec gunicorn wsgi:server --bind :$PORT
```

### Step 4. Modify `requirements.txt`

Add `gunicorn` to the list of dependencies in `requirements.txt`.


At this stage, the root path of your app should have this structure:

```
root\
- app.py
- requirements.txt
- wsgi.py
- Dockerfile
- ....py  # (Other scripts that your Fast Dash app needs)
```

### Step 5. Deploy! 🚀

If the `gcloud` CLI was correctly installed in step 1, simply run this command from the root of your project directory:

```
gcloud run deploy
```

You will be asked to enter a few different settings for your app. Read Google Cloud Run's documentation here to understand what each of them mean.

Generally, choosing the following settings is acceptable:

1. Source code location: Enter the directory with `Dockerfile`. If you are already in the project `root`, then this directory is preselected. Simply hit `Enter`.
2. Service name: Type the app name of hit `Enter` to select default.
3. Please specify a region: Choose the number corresponding to your nearest region.
4. Allow unauthenticated invocations to: Select `y` if you understand and are okay with the repercussions.

That's it! Google Cloud will build your app inside a Docker container and display the URL here once it's ready. The entire operation can take upto 5 minutes for simple applications. The build time highly depends on the complexity of your app and the number of dependencies.