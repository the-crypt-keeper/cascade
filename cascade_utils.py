from transformers import AutoTokenizer
import aiohttp
import os

API_BASE_URL = os.getenv('OPENAI_BASE_URL',"http://100.109.96.89:3333/v1")
API_KEY = os.getenv('OPENAI_API_KEY', "xx-ignored")

async def universal_llm_request(completion, model, messages, params):
    payload = { 'model': model, 'messages': messages, **params }
    headers = { 'Authentication': 'Bearer '+API_KEY }

    async with aiohttp.ClientSession() as session:
        if completion:
            payload['prompt'] = payload.pop('messages')[0]['content']            
            async with session.post(API_BASE_URL+'/completions', json=payload, headers=headers) as resp:
                response = await resp.json()
        else:
            async with session.post(API_BASE_URL+'/chat/completions', json=payload, headers=headers) as resp:
                response = await resp.json()
    
    if 'choices' in response:
        # OpenAI-style response
        answers = [x['message']['content'] if 'message' in x else x['text'] for x in response['choices']]
    elif 'content' in response:
        # LlamaCpp legacy style response
        answers = [response['content']]
    else:
        print(response)
        answers = None
        
    return answers
   
class InternalTokenizer:    
    def __init__(self, name, fn):
        self.fn = fn
        self.name_or_path = name
        
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, bos_token=''):
        system = [x['content'] for x in messages if x['role'] == 'system']
        user = [x['content'] for x in messages if x['role'] == 'user']
        assistant = [x['content'] for x in messages if x['role'] == 'assistant']
        
        system = "You are a helpful assistant." if len(system) == 0 else system[0]
        user = user[0]
        assistant = "" if len(assistant) == 0 else assistant[0]
        
        return self.fn(system, user, assistant)

tokenizer_internal = {
    'internal:vicuna': InternalTokenizer('vicuna', lambda system, user, assistant:
f"""SYSTEM: {system}

USER: {user}

A:{assistant}"""),

    'internal:alpaca': InternalTokenizer('alpaca', lambda system, user, assistant:
f"""### Instruction:
{system}

### Input:
{user}

### Response:{assistant}""")
}

def build_tokenizer(tokenizer_name):
    if tokenizer_name is None:
        return None
    elif tokenizer_name in tokenizer_internal:
        return tokenizer_internal[tokenizer_name]
    else: 
        return AutoTokenizer.from_pretrained(tokenizer_name, trust_remote_code=True)