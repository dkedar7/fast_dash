from fast_dash import FastDash
from fast_dash.Components import Text
from utils import translate

def translate_to_french(english_sentence):
    french_translation = translate(english_sentence)
    return french_translation

app = FastDash(callback_fn=translate_to_french, inputs=Text, outputs=Text, title='Translate to French')

if __name__ == '__main__':
    app.run()