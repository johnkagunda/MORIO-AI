import requests

# Simple form data test
response = requests.post(
    'http://localhost:8000/api/chat/send/',
    data={'prompt': 'What is 2+2?', 'model': 'llama2'}
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")