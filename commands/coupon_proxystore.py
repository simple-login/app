from app.models import Coupon
from app.utils import random_words


for i in range(200):
    code = random_words(5)
    Coupon.create(code=code, comment="For Proxystore", commit=True)
    print(code)
