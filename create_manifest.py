import glob, os, hashlib, json

repo_path = 'repo/'
manifest = {}
manifest['packages'] = []

def hash_file(filename):
    hash = hashlib.sha256()
    with open (filename, 'rb') as file:
        for chunk in iter(lambda: file.read(4096), b""):
            hash.update(chunk)
    return hash.hexdigest() 


if os.path.isfile("order.txt"):
    with open ('order.txt', 'r') as orderfile:
        for item in orderfile:
            file_hash = hash_file((repo_path + item).rstrip())   
            file_name = os.path.basename((repo_path + item).rstrip())
            print (file_name)
            print (file_hash)
            manifest['packages'].append({
                'name': file_name,
                'path': item,
                'hash': file_hash
                })

with open ('manifest.json', 'w') as outfile:
    json.dump(manifest, outfile)
    outfile.close()
