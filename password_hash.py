import bcrypt

password = "AppAdmin2025!"
hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()

print(hash)