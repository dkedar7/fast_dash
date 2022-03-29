import numpy as np
import matplotlib.pyplot as plt
from transformers import pipeline
from io import BytesIO
import base64
import bbox_visualizer as bbv

from PIL import Image


model = pipeline("object-detection")


# colors for visualization
COLORS = [[0.000, 0.447, 0.741], [0.850, 0.325, 0.098], [0.929, 0.694, 0.125],
          [0.494, 0.184, 0.556], [0.466, 0.674, 0.188], [0.301, 0.745, 0.933]]


def load_image_base64(base64_str, size=None, scale=None):
    img = Image.open(BytesIO(base64.b64decode(base64_str))).convert('RGB')
    if size is not None:
        img = img.resize((size, size), Image.ANTIALIAS)
    elif scale is not None:
        img = img.resize((int(img.size[0] / scale), int(img.size[1] / scale)), Image.ANTIALIAS)
    return img


def plot_results(image_contents):

    image_type, image_contents = image_contents.split(',')
    
    pil_img = load_image_base64(image_contents)
    outputs = model(pil_img)
    
    boxes = [(output['box']['xmin'], output['box']['ymin'], output['box']['xmax'], output['box']['ymax']) for output in outputs]
    probs = [output['score'] for output in outputs]
    labels = [output['label'] for output in outputs]
    
    o = bbv.draw_multiple_rectangles(np.array(pil_img), boxes, is_opaque=True)
    bbv.add_multiple_labels(o, labels, boxes, draw_bg=True)
    oi = Image.fromarray(o)
    
    return oi