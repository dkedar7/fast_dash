from transformers import pipeline
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

# Need to import model and tokenizer because default model isn't available for English-Spanish translation
tokenizer = AutoTokenizer.from_pretrained("Helsinki-NLP/opus-mt-en-es")
model = AutoModelForSeq2SeqLM.from_pretrained("Helsinki-NLP/opus-mt-en-es")

en_fr_translator = pipeline("translation_en_to_fr")
en_es_translator = pipeline("translation_en_to_es", tokenizer=tokenizer, model=model)
en_de_translator = pipeline("translation_en_to_de")


def translate(sentence, language):
    "Translate English sentences to French, Spanish and German"

    if language == 'French':
        translation = en_fr_translator(sentence)
        translation_text = translation[0]['translation_text']

    elif language == 'Spanish':
        translation = en_es_translator(sentence)
        translation_text = translation[0]['translation_text']

    elif language == 'German':
        translation = en_de_translator(sentence)
        translation_text = translation[0]['translation_text']

    else:
        translation_text = 'Select a model to continue.'
    
    return translation_text