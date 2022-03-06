from transformers import pipeline

en_fr_translator = pipeline("translation_en_to_fr")

def translate(sentence):
    translation = en_fr_translator(sentence)
    translation_text = translation[0]['translation_text']
    return translation_text