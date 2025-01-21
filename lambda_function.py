from datetime import datetime, timedelta
import json
import os
import boto3
from botocore.exceptions import ClientError

# from dotenv import load_dotenv
import requests
from openai import OpenAI

# load_dotenv()

# Initialize AWS services
s3 = boto3.client("s3")

# Constants
SUBREDDITS = [
    "SomebodyMakeThis",
    "AppIdeas",
    "Doesthisexist",
    "lightbulb",
    "INAT",
    "software",
    "SideProject",
    "InternetIsBeautiful",
    "Startup_Ideas",
    "challengeaprogrammer",
    "androidapps",
    "IdeaHunt",
    "startups",
    "Entrepreneur",
    "WebDev",
    "opensource",
    "coding",
    "computerscience",
    "Business_Ideas",
]

PROMPT = """
For the provided Reddit data, analyze and extract business opportunities using these filters:

MARKET CRITERIA:
- Posts with score > 5 OR multiple similar posts within {timeframe}
- Contains phrases indicating active search ("looking for", "alternative to", "need", "want", "wish")
- Has specific use case or workflow description

FEASIBILITY FILTERS:
- Solution can be prototyped within 2 months
- Uses standard technology stack (no specialized hardware/infrastructure)
- Clear core functionality that solves one specific problem
- No dependencies on large-scale data or complex integrations

VALIDATION SIGNALS:
- Multiple users expressing similar needs
- Mentions of failed attempts to find existing solutions
- Users describing current workarounds
- Detailed description of pain points

For each matching opportunity, format the output as:

PROBLEM:
[Clear 1-sentence problem statement]

TARGET USERS:
[Specific description of who needs this]

VALIDATION:
[List of supporting evidence from posts]

MVP SCOPE:
[Core features for minimum viable solution]

VERIFICATION METHOD:
[How to quickly test market interest]

Sort results by: (Post Score * Number of Similar Posts)
"""


def get_secret(secret_name):
    """Retrieve secret from AWS Secrets Manager"""
    session = boto3.session.Session()
    client = session.client(
        service_name="secretsmanager",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )

    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        raise e
    else:
        if "SecretString" in get_secret_value_response:
            return json.loads(get_secret_value_response["SecretString"])
    return None


def generate_insights(data, openai_client):
    """Generate insights using OpenAI API"""
    try:
        completions = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "developer", "content": PROMPT},
                {"role": "user", "content": str(data)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "insights_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "insights": {
                                "description": "Generated insights items. Multiple items are allowed.",
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "problem": {
                                            "type": "string",
                                            "description": "Clear 1-sentence problem statement",
                                        },
                                        "target_users": {
                                            "type": "string",
                                            "description": "Specific description of who needs this",
                                        },
                                        "validation": {
                                            "type": "string",
                                            "description": "Supporting evidence from posts. Split points with newlines.",
                                        },
                                        "mvp_scope": {
                                            "type": "string",
                                            "description": "Core features for minimum viable solution. Split points with newlines.",
                                        },
                                        "verification_method": {
                                            "type": "string",
                                            "description": "How to quickly test market interest",
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        )
        return json.loads(completions.choices[0].message.content)
    except Exception as e:
        print(f"Error generating insights: {str(e)}")
        return {"insights": []}


def scrape_subreddit(subreddit: str):
    """Scrape data from a subreddit"""
    week_ago = int((datetime.now() - timedelta(days=7)).timestamp())
    url = f"https://api.pullpush.io/reddit/search/submission/?subreddit={subreddit}&size=20&after={week_ago}&sort_type=score"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()["data"]

        return [
            {
                "title": post.get("title"),
                "text": post.get("selftext"),
                "subreddit": post.get("subreddit"),
                "date": datetime.fromtimestamp(post.get("created_utc")).isoformat(),
                "score": post.get("ups"),
            }
            for post in data
        ]
    except Exception as e:
        print(f"Error scraping subreddit {subreddit}: {str(e)}")
        return []


def save_to_s3(data, bucket, key):
    """Save results to S3"""
    try:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(data, indent=4),
            ContentType="application/json",
        )
        return True
    except Exception as e:
        print(f"Error saving to S3: {str(e)}")
        return False


def lambda_handler(event, context):
    """Main Lambda handler"""
    try:
        # Get configuration from environment or event
        output_bucket = os.environ.get("OUTPUT_BUCKET")
        if not output_bucket:
            return {
                "statusCode": 500,
                "body": json.dumps("OUTPUT_BUCKET environment variable not set"),
            }

        openai_key = os.environ.get("OPENAI_API_KEY")
        if not openai_key:
            return {
                "statusCode": 500,
                "body": json.dumps("OPENAI_API_KEY environment variable not set"),
            }

        openai_client = OpenAI(api_key=openai_key)

        # Process subreddits
        collected_data = []
        for subreddit in SUBREDDITS:
            print(f"Processing subreddit: {subreddit}")

            data = scrape_subreddit(subreddit)
            print(data)
            if data:
                insights = generate_insights(data, openai_client)
                collected_data.extend(insights.get("insights", []))

        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        key = f"reddit_insights_{timestamp}.json"

        if save_to_s3(collected_data, output_bucket, key):
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "message": "Analysis completed successfully",
                        "output_location": f"s3://{output_bucket}/{key}",
                        "subreddits_processed": len(collected_data),
                    }
                ),
            }
        else:
            return {
                "statusCode": 500,
                "body": json.dumps("Failed to save results to S3"),
            }

    except Exception as e:
        return {"statusCode": 500, "body": json.dumps(f"Error: {str(e)}")}
