from lambda_function import lambda_handler
from dotenv import load_dotenv

load_dotenv()


# Mock Lambda context
class MockContext:
    def get_remaining_time_in_millis(self):
        return 900000  # 15 minutes in milliseconds


# Test event
event = {}
context = MockContext()

# Run the handler
response = lambda_handler(event, context)
print(response)
