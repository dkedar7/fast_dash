from fast_dash import FastDash
from fast_dash.Components import Image, UploadImage
from utils import plot_results

# 1. Inference function
def image_to_image(image):
    return image

# 2. Define components and initialize app
app = FastDash(callback_fn=plot_results, 
               inputs=UploadImage, 
               outputs=Image,
               title='OBJECT DETECTION',
               title_image_path='https://raw.githubusercontent.com/dkedar7/fast_dash/examples/examples/Object%20detection/assets/icon.webp',
               subheader='Build ML prototypes lightning fast!',
               github_url='https://github.com/dkedar7/fast_dash/',
               linkedin_url='https://linkedin.com/in/dkedar7/',
               twitter_url='https://twitter.com/dkedar7/',
               theme='SKETCHY')

# 3. Deploy!
app.run()