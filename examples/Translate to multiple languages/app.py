from fast_dash import FastDash, Fastify
from fast_dash.Components import Text

import dash_bootstrap_components as dbc

from utils import translate

# Fastify Dash's dropdown component
fast_dropdown = Fastify(DashComponent=dbc.Select, modify_property='value', options={x:x for x in ['French', 'Spanish', 'German']})

def translate_from_english(english_sentence, select_language):
    translation = translate(english_sentence, select_language)
    return translation

app = FastDash(callback_fn=translate_from_english, inputs=[Text, fast_dropdown], outputs=Text, title='Translate from English')
app.run()