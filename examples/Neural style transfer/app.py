from fast_dash import FastDash, Fastify
from fast_dash.Components import Upload, Image
from dash import dcc

from utils import stylize_image, map_style_model_path

# Fastify Dash's dropdown component
dropdown = Fastify(DashComponent=dcc.Dropdown, modify_property='value', options={x:x for x in map_style_model_path.keys()})

def apply_style(image, style):
    "Callback to apply style to image"
    image_type, image_content = image.split(',')
    styled_image = stylize_image(image_content, style)
    return image, styled_image

app = FastDash(callback_fn=apply_style, 
                inputs=[Upload, dropdown], 
                outputs=[Image, Image], 
                title='Neural Style Transfer',
                title_image_path='https://raw.githubusercontent.com/dkedar7/fast_dash/example-neural-style-transfer/examples/Neural%20style%20transfer/assets/icon.png',
                subheader="Apply styles from well-known pieces of art to your own photos")
app.run()