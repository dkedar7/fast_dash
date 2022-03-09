import base64
from style_transfer import neural_style
from fast_dash.utils import pil_to_b64

# dictionary to save (Name of the style, Path of the model that does style transfer)
map_style_model_path = {'Candy':'saved_models/candy.pth',
                        'Mosaic':'saved_models/mosaic.pth',
                        'Rain Princess':'saved_models/rain_princess.pth',
                        'Udnie': 'saved_models/udnie.pth'}

def stylize_image(input_image_b64_str, model="Mosaic"):
    "Call the main style function from 'style_transfer' path"

    model_path = map_style_model_path.get(model)
    img = neural_style.stylize(input_image_b64_str, model=model_path, content_scale=1)
    img_b64 = pil_to_b64(img)

    return img_b64