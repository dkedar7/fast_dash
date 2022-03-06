from transformers import pipeline

en_fr_translator = pipeline("translation_en_to_fr")
en_es_translator = pipeline("translation_en_to_es")
en_de_translator = pipeline("translation_en_to_de")

def translate(sentence, language):
    "Translate English sentences to French, Spanish and German"

    if language == 'French':
        translation = en_fr_translator(sentence)

    elif language == 'Spanish':
        translation = en_es_translator(sentence)

    elif language == 'German':
        translation = en_de_translator(sentence)

    translation_text = translation[0]['translation_text']
    return translation_text