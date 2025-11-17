import os
from agent_framework.azure import AzureOpenAIChatClient, AgentFunctionApp
from azure.identity import DefaultAzureCredential

endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
if not endpoint:
    raise ValueError("AZURE_OPENAI_ENDPOINT is not set.")

deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT")
if not deployment_name:
    raise ValueError("AZURE_OPENAI_DEPLOYMENT is not set.")

api_key = os.getenv("AZURE_OPENAI_API_KEY")
if not api_key:
    raise ValueError("AZURE_OPENAI_API_KEY is not set.")

# Create an AI agent following the standard Microsoft Agent Framework pattern
agent = AzureOpenAIChatClient(
    endpoint=endpoint,
    deployment_name=deployment_name,
    api_key=api_key,
    credential=DefaultAzureCredential()
).create_agent(
    instructions="You are a helpful assistant that can answer questions and provide information.",
    name="MyDurableAgent"
)

# Configure the function app to host the agent with durable thread management
app = AgentFunctionApp(agents=[agent])
