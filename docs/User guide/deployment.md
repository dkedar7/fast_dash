# Deployment

Fast Dash apps are deployed as any other Flask app. A universal and hence the recommended way to deploy is to containerize the application and then deploy it to an endpoint.

Here're the general steps involved with the deployment process:

1. Extract the Flask server from the `FastDash` app object (`server = app.server`).
2. Add a `Dockerfile` in the same directory that contains the main Fast Dash app module.
3. Build and run Docker container.

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

### Step 3. Create `Dockerfile`

Create a Dockerfile in the current path and modify it to reflect the following:

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

### Step 4. Update `requirements.txt`

Add `gunicorn` to the list of dependencies in `requirements.txt`.

### Step 5. Deploy! 🚀

If the `gcloud` CLI was correctly installed in step 1, simply run this command from the root of your project directory:

```
gcloud run deploy
```

You will be asked to choose a few different settings for your deployment. Read Google Cloud Run's documentation here to understand what each of them mean.

That's it! Google Cloud will build your app inside a Docker container and display the URL once it's ready. The entire operation can take upto five minutes for simple applications. The build time highly depends on the complexity of your app and the number of dependencies.