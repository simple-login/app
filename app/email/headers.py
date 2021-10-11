"""Email headers"""
MESSAGE_ID = "Message-ID"
IN_REPLY_TO = "In-Reply-To"
REFERENCES = "References"
DATE = "date"
SUBJECT = "Subject"
FROM = "From"
TO = "To"
CONTENT_TYPE = "Content-Type"
MIME_VERSION = "Mime-Version"
REPLY_TO = "Reply-To"
RECEIVED = "Received"
CC = "Cc"
DKIM_SIGNATURE = "DKIM-Signature"
X_SPAM_STATUS = "X-Spam-Status"

# headers used to DKIM sign in order of preference
DKIM_HEADERS = [
    [MESSAGE_ID.encode(), DATE.encode(), SUBJECT.encode(), FROM.encode(), TO.encode()],
    [FROM.encode(), TO.encode()],
    [MESSAGE_ID.encode(), DATE.encode()],
    [FROM.encode()],
]
