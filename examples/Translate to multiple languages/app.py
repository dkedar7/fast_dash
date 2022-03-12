from fast_dash import FastDash, Fastify
from fast_dash.Components import Text
from dash import dcc

from utils import translate

# Fastify Dash's dropdown component
dropdown = Fastify(DashComponent=dcc.Dropdown, modify_property='value', options={x:x for x in ['French', 'Spanish', 'German']})

def translate_from_english(english_sentence, select_language):
    translation = translate(english_sentence, select_language)
    return translation

app = FastDash(callback_fn=translate_from_english, inputs=[Text, dropdown], outputs=Text, title='Translate from English')

if __name__ == '__main__':
    app.run()