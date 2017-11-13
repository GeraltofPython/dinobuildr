#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import subprocess, glob, json, os, hashlib, urllib2, base64, re, getpass, stat, shutil, shlex, sys, pwd, grp
from SystemConfiguration import SCDynamicStoreCopyConsoleUser

#### section 1: defining too many variables ######################
# in this section we define way too many variables and things. 
##################################################################

# globalize the uid and gid variables so the DMG installer can use it without needing to pass it every time.
# TODO: this is lazy and a better method should be used. 
global uid 
global gid

local_dir = "/var/tmp/dinobuildr" # the local directory the builder will use
org = "mozilla" # the org that is hosting the build repository
repo = "dinobuildr" # the rep that is hosting the build
branch = "master" # the branch that we are using. useful to change this if developing / testing

script_path = os.path.realpath(__file__) # the path that the script is executed from

os.environ["DINOPATH"] = local_dir # an environment variable for the builder's local directory to be passed on to shells scripts 
current_user = (SCDynamicStoreCopyConsoleUser(None, None, None) or [None])[0] # the name of the user running the script
current_user = [current_user,""][current_user in [u"loginwindow", None, u""]] # same as above, Apple suggests using both methods
uid = pwd.getpwnam(current_user).pw_uid # the UID of the user running the script
gid = grp.getgrnam("staff").gr_gid # the GID of the group "staff" which is the default primary group for all users in MacOS

lfs_url = "https://github.com/%s/%s.git/info/lfs/objects/batch" % (org, repo) # the generic LFS url structure that github uses
raw_url = "https://raw.githubusercontent.com/%s/%s/%s/" % (org, repo, branch) # the generic RAW url structure that github uses
manifest_url= "https://raw.githubusercontent.com/%s/%s/%s/manifest.json" % (org, repo, branch) # the url of the manifest file
manifest_hash = "88cb47c6bfa7af64dae95966de405c21881cb0817e7721085fa61a7a40ef31b2" # the hash of the manifest file
manifest_file = "%s/manifest.json" % local_dir # the expected filepath of the manifest file

# authenticate to github since this is a private repo.
# base64string is really just a variable that stores the username and password in this format: username:password
# TODO: remove this before moving to the production repo (which will be public).

if os.getuid() != 0:
    print "This script requires root to run, please try again with sudo."
    exit(1)

user = raw_input("Enter github username: ").replace('\n','') # we get the github username from the user
password = getpass.getpass("Enter github password or PAT: ") # we securely get the github password or PAT from the user
base64string = base64.encodestring('%s:%s' % (user, password)).replace('\n','') # encode in base64 and store as a variable

#### section 2: functions on functions on functions######################
# in this section we define all the important functions we will use.
######################################################################### 

# the downloader function accepts three arguments: the url of the file you are downloading, the filename (path) of the file you are
# downloading and an optional password if the download requires Basic authentication. the downloader reads the Content-Length 
# portion of the header of the incoming file and determines the expected file size then reads the incoming file in chunks of 
# 8192 bytes and displays the currently read bytes and percentage complete.

def downloader(url, file_path, password=None): # TODO: the password=None bit will not be a thing in production
    if not os.path.exists(local_dir):
        os.makedirs(local_dir)
    download_req = urllib2.Request(url)
    if password: # TODO: not a thing in production since the repo will not be private
        download_req.add_header("Authorization", "Basic %s" % password)
    download = urllib2.urlopen(download_req)
    meta = download.info()
    file_size = int(meta.getheaders("Content-Length")[0])
    print "%s is %s bytes." % (file_path, file_size)
    with open(file_path, 'wb') as code:
        chunk_size = 8192
        bytes_read = 0
        while True:
            data = download.read(chunk_size)
            bytes_read += len(data)
            code.write(data)
            status = r"%10d [%3.2f%%]" % (bytes_read, bytes_read * 100 / file_size)
            status = status + chr(8)*(len(status)+1)
            print "\r", status, 
            if len(data) < chunk_size:
                break

# the package installer function runs the installer binary in MacOS and pipes stdout and stderr to the python console
# the return code of the package run can be found in the pipes object (pipes.returncode). this is the reason we need 
# to run this script with sudo!


def pkg_install(package):
    pipes = subprocess.Popen(["sudo","installer","-pkg",package,"-target","/"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = pipes.communicate()
    print out.decode('utf-8'), err.decode('utf-8'), pipes.returncode

# the script executer executes any .sh file using bash and pipes stdout and stderr to the python console.
# the return code of the script execution can be found in the pipes object (pipes.returncode). 

def script_exec(script):
    pipes = subprocess.Popen(["/bin/bash","-c",script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = pipes.communicate()
    print out.decode('utf-8'), err.decode('utf-8'), pipes.returncode

# the dmg installer is by far the most complicated function, because DMGs are more complicated than
# they probably should be. we mount the dmg with hdiutil and depending on if the dmg has a PKG or a
# .app inside we take the appropriate action. we also have the option to specify an optional command
# since sometimes we must execute installer .apps or pkgs buried in the .app bundle, which is 
# annoying. 

def dmg_install(filename, installer, command=None):
    pipes = subprocess.Popen(["hdiutil","attach",filename], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = pipes.communicate()
    print out.decode('utf-8'), err.decode('utf-8'), pipes.returncode
    volume_path = re.search("(\/Volumes\/).*$", out).group(0) 
    installer_path = "%s/%s" % (volume_path, installer)
    if command != None and installer == '': # this is the bit where we can accept an optional command with arguments
        command = command.replace('${volume}', volume_path).encode("utf-8")
        command = shlex.split(command) 
        pipes = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = pipes.communicate()
        print out.decode('utf-8'), err.decode('utf-8'), pipes.returncode
    if ".pkg" in installer: # if it's an installer, we install it
        installer_destination= "%s/%s" % (local_dir, installer)
        shutil.copyfile(installer_path, installer_destination)
        pkg_install(installer_path)
    if ".app" in installer: # if it's a .app we assume it goes in /Applications
        applications_path = "/Applications/%s" % installer.rsplit('/', 1)[-1]
        if os.path.exists(applications_path):
            shutil.rmtree(applications_path) # useful for testing: if the .app exists, nuke it
        shutil.copytree(installer_path, applications_path)
        os.chown(applications_path, uid, gid) # ownership is all wonky because we run with sudo
        os.chmod(applications_path, 0o755) # so are the permissions
    pipes = subprocess.Popen(["hdiutil","detach",volume_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = pipes.communicate()
    print out.decode('utf-8'), err.decode('utf-8'), pipes.returncode
    
# the hash_file function accepts two arguments: the filename that you need to determine the SHA256 hash of
# and the expected hash it returns True or False.

def hash_file(filename, man_hash):
    if man_hash == "skip":
        print "NOTICE: Manifest file is instructing us to SKIP hashing %s." % filename
    else:     
        hash = hashlib.sha256()
        with open (filename, 'rb') as file:
            for chunk in iter(lambda: file.read(4096), b""):
                hash.update(chunk)
        if hash.hexdigest() == man_hash:
            print "The hash for %s match the manifest file" % filename 
            return True
        else: 
            print "WARNING: The the hash for %s is unexpected." % filename
            exit(1)

# the pointer_to_json function accepts the url of the file in the github repo and the password to the repo.
# the pointer file is read from github then parsed and the "oid sha256" and "size" are extracted from the pointer.
# an object is returned that contains a json request for the file that the pointer is associated with.
# TODO: password should be optional in the prod version.

def pointer_to_json(dl_url, password):
    content_req = urllib2.Request(dl_url)
    content_req.add_header("Authorization", "Basic %s" % password)
    content_result = urllib2.urlopen(content_req)
    output = content_result.read()
    content_result.close()
    oid = re.search('(?m)^oid sha256:([a-z0-9]+)$', output)
    size = re.search('(?m)^size ([0-9]+)$', output)
    json_data = '{"operation": "download", "transfers": ["basic"], "objects": [{"oid": "%s", "size": %s}]}' % (oid.group(1), size.group(1))
    return json_data 

# the get_lfs_url function makes a request the the lfs API of the github repo, receives a JSON response.
# then gets the download URL from the JSON response and returns it.

def get_lfs_url(json_input, password, lfs_url):
    req = urllib2.Request(lfs_url, json_input)
    req.add_header("Authorization", "Basic %s" % password)
    req.add_header("Accept", "application/vnd.git-lfs+json")
    req.add_header("Content-Type", "application/vnd.git-lfs+json")
    result = urllib2.urlopen(req)
    results_python = json.load(result)
    file_url = results_python['objects'][0]['actions']['download']['href']
    result.close()
    return file_url

#### section 3: actually doing stuff! ######################
# now the fun bit: we actually get to do stuff!
############################################################

# if the local directory doesn't exist, we make it.
if not os.path.exists(local_dir):
    os.makedirs(local_dir)

# download the manifest.json file.
downloader(manifest_url, manifest_file, base64string)

# check the hash of the incoming manifest file and bail if the hash doesn't match.
hash_file(manifest_file, manifest_hash)

# we read the manifest file and examine each object in it. if the object is a .pkg file, then we assemble 
# the download url of the pointer, read the pointer and request the file from LFS. if the file we get has a
# hash that matches what's in the manifest, we Popen the installer function if the object is a .sh file, 
# we assemble the download url and download the file directly. if the script we get has a hash that matches 
# what's in the manifest, we set the execute flag and Popen the script_exec function. 

# same with dmgs, although dmgs are real complicated so we may end up running an arbitrary command, copying the installer or 
# installing a pkg.

with open (manifest_file, 'r') as manifest_data:
    data = json.load(manifest_data) # read the manifest file as json, because it's json
    
for item in data['packages']:
    if item['filename'] != "":
        file_name = item['filename'] # if the manifest specifies a filename, we use that
    else: 
        file_name = (item['url'].replace('${version}', item['version'])).rsplit('/', 1)[-1] # otherwise we guess the filename from the url
    
    local_path = "%s/%s" % (local_dir, file_name) # TODO: this variable name is dumb, this is the path to the file we're working with
     
    if item['type'] == "pkg-lfs": # if it's a package in LFS
        dl_url = raw_url + item['url'] # request the pointer from the raw url 
        json_data = pointer_to_json(dl_url, base64string) # parse the pointer
        lfsfile_url = get_lfs_url(json_data, base64string, lfs_url) # figure out the actual url
        print "Downloading:", item['item']
        downloader(lfsfile_url, local_path) # download package
        hash_file(local_path, item['hash']) # hash package
        pkg_install(local_path) # install package
    
    if item['type'] == "shell": # if it's a shells cript
        dl_url = raw_url + item['url'] # assume it's in github so assume it's raw url
        print "Downloading:", item['item']
        downloader(dl_url, local_path, base64string) # download it
        hash_file(local_path, item['hash']) # hash it
        print "Executing:", item['item']
        perms = os.stat(local_path) # set permissions to we can execute it
        os.chmod(local_path, perms.st_mode | stat.S_IEXEC) # see above
        script_exec(local_path) # execute it
    
    if item['type'] == "dmg": # if it's a dmg
        if item['url'] == '': # TODO: consisitency: there should be URL checks everywhere or do this in the manifest generator
            print "No URL specified for %s" % item['item']
            break
        if item['dmg-installer'] == '' and item['dmg-advanced'] == '': # EITHER dmg-installer or dmg-advanced is required
           print "No installer or install command specified for %s" % item['item']
           break
        dl_url = item['url'].replace('${version}', item['version']) # get the download url from the manifest 
        print "Downloading:", item['item']
        downloader(dl_url, local_path) # download dmg
        hash_file(local_path, item['hash']) # hash dmg
        print local_path
        print item['dmg-installer']
        if item['dmg-installer'] != '': # if it's a regular dmg (pkg or .app) let the installer handle it
            dmg_install(local_path, item['dmg-installer']) 
        if item['dmg-advanced'] != '': # if it's fancier than that, defer to the dmg-advanced property
            dmg_install(local_path, '', item['dmg-advanced'])

    if item['type'] == "file-lfs": # if it's a file in lfs
        if item['url'] == '':
            print "No URL specified for %s" % item['item']
            break
        dl_url = raw_url + item['url'] # infer it's raw url
        json_data = pointer_to_json(dl_url, base64string) # get the pointer from the raw url
        lfsfile_url = get_lfs_url(json_data, base64string, lfs_url) # get the download url from the pointer
        print "Downloading:", item['item']
        downloader(lfsfile_url, local_path) # download the file
        hash_file(local_path, item['hash']) # hash the file

# delete the temporary directory we've been downloading packages into.
print "Cleanup: Deleting %s" % local_dir
shutil.rmtree(local_dir)
