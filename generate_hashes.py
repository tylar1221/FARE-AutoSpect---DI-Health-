# generate_hashes.py
import bcrypt

# Generate hash for 'admin123'
admin_hash = bcrypt.hashpw("admin123".encode('utf-8'), bcrypt.gensalt())
print(f"admin123 → {admin_hash.decode()}")

# Generate hash for 'invest123'
invest_hash = bcrypt.hashpw("invest123".encode('utf-8'), bcrypt.gensalt())
print(f"invest123 → {invest_hash.decode()}")