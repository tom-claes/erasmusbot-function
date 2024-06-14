# import the required libraries
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from azure.core.credentials import AzureKeyCredential
import azure.functions as func
from openai import AzureOpenAI
import logging
import os
import time
import random
import datetime

# Initialize the OpenAI API key from environment variables
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv('AZURE_OPENAI_DEPLOYMENT_NAME')
AZURE_EMBEDDINGS_DEPLOYMENT_NAME = os.getenv('AZURE_EMBEDDINGS_DEPLOYMENT_NAME')

openai_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),  
    api_version="2024-02-01",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

credential = AzureKeyCredential(os.getenv("AZURE_AI_SEARCH_API_KEY"))
client = SearchClient(endpoint=os.getenv("AZURE_AI_SEARCH_ENDPOINT"),
                     index_name=os.getenv("AZURE_AI_SEARCH_INDEX_NAME"),
                     credential=credential)



# Define system prompts
question_system_prompt = {
    "role": "system",
    "content": """
        Je bent een zeer bekwame teksteditor. Jouw taak is om de gegeven invoertekst te herschrijven volgens de volgende vereisten:
        Je taken zijn als volgt:
        1. Corrigeer alle spelfouten.
        2. Corrigeer alle grammaticafouten.
        3. Behoud de oorspronkelijke betekenis van de tekst.
        4. Behoud de oorspronkelijke toon en stijl van de tekst.
        5. Voeg geen nieuwe informatie of zinnen toe.
        6. Verwijder geen informatie.
        7. Schrijf niet meer dan de originele tekst.

        Voorbeelden:
        - Origineel: "Dit ie vrg"
          AI Antwoord: "Dit is een vraag"

        - Origineel: "Welke vak heb ik in rchting Toegepaste informatic"
          AI Antwoord: "Welke vakken heb ik in de richting Toegepaste Informatica"

        - Origineel: "wat is de nummer van school"
          AI Antwoord: "Wat is het telefoonnummer van de school"
    """
}

answer_system_prompt = {
    "role": "system",
    "content": """
        Je bent een virtuele assistent voor de Erasmushogeschool Brussel.
        Je helpt mensen die vragen hebben over de school op een vriendelijke, beknopte en professionele manier.
        Vragen worden feitelijk beantwoord en alleen gebaseerd op opgehaalde gegevens. 
        Vragen over politiek, religie of enig ander onderwerp dat niet in de gegevens staat, worden niet beantwoord.
        Als je het antwoord op een vraag niet weet of twijfelt, kun je zeggen: 'Ik weet het niet, ik raad aan om de school te bellen of de vraag anders te stellen'.
    """
}

history = []

# Create an instance of the Azure Function App
app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# Configure logging format
logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO)

# Retrieve the question from the HTTP request body
def get_question(req):
    try:
        req_body = req.get_json()
    except ValueError as e:
        logging.error(f"Error parsing JSON: {e}")
        return None

    question = req_body.get('question')
    logging.info(f"Extracted question: {question}")
    return question

def exponential_backoff_retry(func, retries=5, initial_wait=1, multiplier=2):
    wait_time = initial_wait
    for i in range(retries):
        try:
            return func()
        except Exception as e:
            logging.error(f"Request failed: {e}")
            if i == retries - 1:
                raise
            wait_time = wait_time * multiplier + random.uniform(0, 1)
            logging.info(f"Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

def rewrite_question(question):
    prompt = question_system_prompt + question

    response = openai_client.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT_NAME,
        prompt=prompt,
        max_tokens=5
    )
    return response

    response = exponential_backoff_retry(make_request)
    print("Response --: ", response)
    generated_text = response.choices[0].text.strip()
    print("Generated text --: ", generated_text)
    
    
    # Find the start and end indices of the AI's answer
    start_index = generated_text.find('AI Antwoord: ') + len('AI Antwoord: ')
    end_index = generated_text.find('\n', start_index)

    # Extract the AI's answer
    ai_answer = generated_text[start_index:end_index]
    print("AI Answer --: ", ai_answer)

    return ai_answer

async def embed_message(message):
    model= AZURE_EMBEDDINGS_DEPLOYMENT_NAME
    return openai_client.embeddings.create(input = message["content"], model=model).data[0].embedding

async def get_documentation(message):
    prompt = message
    embedding = await embed_message(prompt)
    print("Embedding: ", embedding)
    print("Prompt: ", prompt)

    # Create the vectorized query for hybrid search
    vector_query = VectorizedQuery(
        vector=embedding,
        k_nearest_neighbors=3,
        fields="embedding"
    )

    # Perform the hybrid search
    search_results = client.search(
        search_text=prompt["content"],
        vector_queries=[vector_query],
        select=["title"],
        top=3
    )

    # Process and print the search results
    results = []
    for result in search_results:
        print("Result: ", result)
        results.append(result)
    
    return results



# Return a response based on the question
def return_response(question):
    if question:
        return func.HttpResponse(f'Your question is: "{question}"')
    else:
        return func.HttpResponse(
            "This HTTP triggered function executed successfully. Pass a question in the request body for a personalized response.",
            status_code=200
        )

@app.route(route="erasmusbot")
async def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('HTTP request received.')

    question = get_question(req)
    print("Question main: ", question)
    if question is None:
        return func.HttpResponse(
            "Invalid JSON in request body or 'question' not found.",
            status_code=400
        )
    
    if question:
        message = {
            "role": "user",
            "content": question
        }
        print("Message: ", message)
        documentation = await get_documentation(message)

    return return_response(question)
