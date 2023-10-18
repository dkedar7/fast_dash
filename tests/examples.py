from fast_dash import FastDash, Fastify
from fast_dash.Components import Text, Image, Upload, UploadImage, Slider, html, dcc
from fast_dash.utils import _pil_to_b64


def example_1_simple_text_to_text():
    "Fast Dash example 1. Simple text to text Fast Dash app"
    ## Define callback functions
    def simple_text_to_text_function(input_text):
        return input_text

    app = FastDash(
        callback_fn=simple_text_to_text_function,
        inputs=Text,
        outputs=Text,
        title="Fast Dash example 1",
    )

    return app


def example_2_text_with_slider():
    "Fast Dash example 2"

    # Step 1: Define your model inference
    def text_to_text_function(input_text, slider_value):
        processed_text = f"{input_text}. Slider value is {slider_value}."
        return processed_text

    # Step 2: Specify the input and output components
    app = FastDash(
        callback_fn=text_to_text_function,
        inputs=[Text, Slider],
        outputs=Text,
        title="Fast Dash example 2",
    )

    return app


def example_3_image_to_image():
    "Fast Dash example 3"

    # Step 1: Define your model inference
    def callback_fn(image):
        return image

    # Step 2: Specify the input and output components
    app = FastDash(
        callback_fn=callback_fn,
        inputs=Upload,
        outputs=Image,
        title="Fast Dash example 3",
    )

    return app


def example_4_image_slider_to_image_text():
    "Fast Dash example 4. Input is Upload (with ack) and slider. Output is Image and Text."

    def callback_fn(input_text, slider_value):
        return input_text, f"Slider value is {slider_value}"

    ack_image = Fastify(html.Img(width="100%"), "src")
    fast_upload = Fastify(
        dcc.Upload(
            children=["Click to upload"],
            style={"borderStyle": "dashed", "padding-bottom": "20px"},
        ),
        "contents",
        ack=ack_image,
    )

    app = FastDash(
        callback_fn=callback_fn,
        inputs=[fast_upload, Slider],
        outputs=[Image, Text],
        title="Fast Dash example 4",
        theme="SKETCHY",
    )

    return app


def example_5_uploadimage_to_image():
    "Fast Dash example 5. Input is UploadImage. Output is Image."

    def image_to_image(image):

        from PIL import Image
        import io
        import base64

        _, image_contents = image.split(",")
        processed_image = Image.open(
            io.BytesIO(base64.b64decode(image_contents.encode()))
        )

        return _pil_to_b64(processed_image)

    app = FastDash(
        callback_fn=image_to_image,
        inputs=UploadImage,
        outputs=Image,
        title="Fast Dash example 5",
        title_image_path="https://storage.googleapis.com/fast_dash/0.2.7/Mosaic%20examples/ex1.png",
        subheader="Build ML prototypes lightning fast!",
        github_url="https://github.com/dkedar7/fast_dash/",
        linkedin_url="https://linkedin.com/in/dkedar7/",
        twitter_url="https://twitter.com/dkedar7/",
        theme="FLATLY",
    )

    return app


def example_6_text_to_plt():
    "Fast Dash example 5. Input is UploadImage. Output is Image."

    import matplotlib.pyplot as plt

    def text_to_plt(some_text) -> plt.Figure:

        fig, ax = plt.subplots(1, 1)
        ax.plot([1, 2, 3], [4, 5, 6])

        return fig

    app = FastDash(
        callback_fn=text_to_plt,
        inputs=Text,
        outputs=Image,
        title="Fast Dash example 6",
        disable_logs=True
    )

    return app
