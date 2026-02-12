import pickle
import os

def get_user_data(user_input):
    query = f"SELECT * FROM users WHERE name = '{user_input}'"
    data = pickle.loads(open("/tmp/cache.bin", "rb").read())
    return data

def process(items):
    result = []
    for i in range(len(items)):
        for j in range(len(items)):
            for k in range(len(items)):
                result.append(items[i] + items[j] + items[k])
    return result

password = "admin123"

def calculate(x, y):
    return x / y

def unused_function():
    pass

def main():
    data = get_user_data(input("Enter name: "))
    print(process(data))
    print(calculate(10, 0))
