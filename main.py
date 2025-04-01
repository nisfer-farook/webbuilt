# pip install "python-telegram-bot[job-queue]" python-telegram-bot asyncio pathlib aiohttp yt_dlp humanize requests schedule
API_TOKEN = "8152120810:AAGzw-FpuKgRBe9Cy0L_ePLde6TLYnLfjwE"
ADMIN_IDs = ["1129730859", "7024110377"]
import yt_dlp
import subprocess
import aiohttp
import asyncio
import os
import re
import shutil
from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth
import xml.etree.ElementTree as ET
from pathlib import Path
import time
import humanize
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ContextTypes
import sys
import re
from urllib.parse import unquote
import schedule
import threading

sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')

# ______________________________________________________ Pre Defined ______________________________________________________
cookies_path = "cookies.txt"
USER_DELETE_PREFERENCE = dict()
# _________________________________________________________________________________________________________________________
def clear_folder(folder_path: str):
    if not os.path.exists(folder_path):
        return  "Folder is already Empty!"

    for item in os.listdir(folder_path):
        item_path = os.path.join(folder_path, item)
        if os.path.isfile(item_path) or os.path.islink(item_path):
            os.remove(item_path)  # Remove files and symlinks
        elif os.path.isdir(item_path):
            shutil.rmtree(item_path)  # Remove subdirectories
    return  "Your Storage space cleared!"

def clean_string(input_string):
    # Define the characters to replace and their replacements
    replacements = {
        '|': '-',
        '?': '!',
        '#': '*',
        ',': '-',
        '&': 'and',    # Example replacement for special character
        '@': 'at'      # Add more replacements as needed
    }
    # Perform replacements
    for old_char, new_char in replacements.items():
        input_string = input_string.replace(old_char, new_char)
    return input_string

def is_youtube_link(user_input):
    youtube_regex = r'^(https?:\/\/)?(www\.)?(m\.)?(youtube\.com|youtu\.be|you\.be)\/.+$'
    return bool(re.match(youtube_regex, user_input))
def get_folder_size(folder_path):
    return sum(f.stat().st_size for f in Path(folder_path).rglob('*') if f.is_file())
def format_size(bytes_size):
    if bytes_size < 1024:  # Bytes
        return f"{bytes_size} B"
    elif bytes_size < 1024**2:  # KB
        return f"{bytes_size / 1024:.2f} KB"
    elif bytes_size < 1024**3:  # MB
        return f"{bytes_size / (1024**2):.2f} MB"
    else:  # GB
        return f"{bytes_size / (1024**3):.2f} GB"
def get_time_ago(info_dict):
    upload_date = info_dict.get('upload_date')
    upload_datetime = datetime.strptime(upload_date, '%Y%m%d')
    current_datetime = datetime.now()
    time_diff = current_datetime - upload_datetime
    return humanize.naturaltime(time_diff)

def format_view_count(view_count):
    if view_count >= 1_000_000_000:
        return f"{view_count / 1_000_000_000:.1f}B"  # Billions
    elif view_count >= 1_000_000:
        return f"{view_count / 1_000_000:.1f}M"  # Millions
    elif view_count >= 1_000:
        return f"{view_count / 1_000:.1f}K"  # Thousands
    else:
        return str(view_count)
def format_duration(duration_in_seconds):

    # Calculate hours, minutes, and seconds
    hours = duration_in_seconds // 3600
    minutes = (duration_in_seconds % 3600) // 60
    seconds = duration_in_seconds % 60
    
    # Build the duration string
    duration_str = ""
    if hours > 0:
        duration_str += f"{hours}h "
    if minutes > 0:
        duration_str += f"{minutes}m "
    if seconds > 0 or (hours == 0 and minutes == 0):
        duration_str += f"{seconds}s"
    
    return duration_str.strip()

def delete_file_from_nextcloud(webdav_url, username, password, save_name, local_file_path, job):
    """Deletes a file from Nextcloud via WebDAV."""
    try:
        response = requests.delete(f"{webdav_url}temp/{save_name}", auth=(username, password))
        if response.status_code in (200, 204, 404):  # 404 means already deleted
            print(f"File '{save_name}' deleted from Nextcloud successfully.")
        else:
            print(f"Failed to delete file '{save_name}' from Nextcloud. Status: {response.status_code}, Response: {response.text}")
    except Exception as e:
        print(f"Error deleting file '{save_name}' from Nextcloud: {e}")
    finally:
        if os.path.exists(local_file_path): # Check to make sure the file is still there, avoids race condition.
           try:
                os.remove(local_file_path)
           except Exception as e:
               print(f"local file '{local_file_path}' delete error: {e}.")
    try:
        # After deletion, cancel the job so it doesn't run again
        schedule.cancel_job(job)
    except Exception as e:
        print(f"Error in cancelling done jobs {e}")

def schedule_file_deletion(webdav_url, username, password, save_name, local_file_path):
    """Schedules the deletion of a file after 30 minutes."""
    # Use threading so the schedule doesn't block main program.
    def run_threaded(job_func):
        job_thread = threading.Thread(target=job_func)
        job_thread.start()

    # Create the job to delete the file
    job = schedule.every(30).minutes.do(
        run_threaded, 
        lambda: delete_file_from_nextcloud(webdav_url, username, password, save_name, local_file_path, job)
    )

    # Run the pending scheduled task in a separate thread.
    def run_pending():
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute. Can be shorter or longer.

    thread = threading.Thread(target=run_pending)
    thread.start()

async def get_public_share_link(nextcloud_url, username, password, save_name):
    headers = {"OCS-APIRequest": "true"}
    payload = {"path": f"/temp/{save_name}", "shareType": 3, "permissions": 1 }

    response = requests.post(f"https://oto.lv.tab.digital/ocs/v2.php/apps/files_sharing/api/v1/shares", auth=(username, password), headers=headers, data=payload)
    if response.status_code == 200:

        share_link = ET.fromstring(response.content).find(".//url").text
        return f"{share_link}/download"
    else:
        return f"Failed to upload. Status code: {response.status_code}\nResponse text: {response.text}"

async def handle_message(update: Update, context: CallbackContext, user_message, user_id):
    return_text = ""
    if is_youtube_link(user_message):
        status_msg = await update.message.reply_text("Looking for your link...")
        asyncio.create_task(ytdlp_sd_download(update, context, status_msg, user_message))
        return return_text
    return user_message

async def background_download(update: Update, context: CallbackContext, status_msg, user_folder: Path, file_url: str, attemptNumber) -> None:
    """Performs the download in the background and updates the user about the progress."""
    # File size limit in bytes (5GB)
    MAX_FILE_SIZE = 5 * 1024 * 1024 * 1024

    try:
        # Send a HEAD request to get file metadata
        async with aiohttp.ClientSession() as session:
            async with session.head(file_url, allow_redirects=True) as head_resp:
                if head_resp.status != 200:
                    if attemptNumber > 3:
                        await status_msg.edit_text(f"Failed to access file. Status code: {head_resp.status}\n🔄 Attempting failed! ({attemptNumber}) | Attempt number reached its maximum limit!")
                        return 
                    await status_msg.edit_text(f"Failed to access file. Status code: {head_resp.status}\n🔄 Re-attempting ({attemptNumber})")
                    return await background_download(update, context, status_msg, user_folder, file_url, attemptNumber+1)

                # Extract file name from Content-Disposition header
                content_disposition = head_resp.headers.get('Content-Disposition')
                if content_disposition and 'filename=' in content_disposition:
                    file_name = content_disposition.split('filename=')[-1].strip('"').strip("'")
                else:
                    # Fallback to extracting from the URL and clean the filename
                    file_name = file_url.split('/')[-1] or "unknown_file"
                    # Remove URL parameters (everything after ?)
                    file_name = file_name.split('?')[0]
                    # Decode URL encoding
                    file_name = unquote(file_name)
                    # Optionally: limit the filename length to avoid system restrictions
                    file_name = file_name[:255]

                # Check file size before downloading
                content_length = head_resp.headers.get('Content-Length')
                if content_length and int(content_length) > MAX_FILE_SIZE:
                    await status_msg.edit_text(f"File is too large to download (limit: {MAX_FILE_SIZE / (1024 ** 3)}GB).")
                    return

            # Proceed with the download
            file_path = user_folder / file_name
            async with aiohttp.ClientSession() as session:
                async with session.get(file_url, allow_redirects=True) as resp:
                    if resp.status != 200:
                        await status_msg.edit_text(f"Failed to download file. Status code: {resp.status}")
                        return

                    with open(file_path, 'wb') as file:
                        downloaded = 0
                        content_length = int(content_length) if content_length else None
                        last_reported_percentage = 0
                        last_update_time = asyncio.get_running_loop().time()
                        xc = True

                        # Download in chunks
                        async for chunk in resp.content.iter_chunked(8192):
                            file.write(chunk)
                            downloaded += len(chunk)

                            # Report download progress every 2 seconds
                            current_time = asyncio.get_running_loop().time()
                            if content_length and current_time - last_update_time >= 0.5:
                                percentage = (downloaded / content_length) * 100
                                bar_length = 15  # Length of the progress bar 
                                filled_length = int(bar_length * downloaded // content_length)
                                bar = '■' * filled_length + '□' * (bar_length - filled_length)
                                try:
                                    await status_msg.edit_text(
                                        f"Downloading...\n⬇️ |{bar}| {percentage:.2f}% ({format_size(content_length)})"
                                    )
                                except:
                                    pass
                                last_update_time = current_time
                            else:
                                if xc:
                                    if content_length:
                                        await status_msg.edit_text(f"Downloading...")
                                    else:
                                        await status_msg.edit_text(f"Downloading... (Unknown File Size)")
                                    xc = False


            # Notify user of successful download
            await status_msg.edit_text(f"✅ **Download Completed!** ({format_size(os.path.getsize(file_path))})", parse_mode='Markdown')
            #await status_msg.edit_text(f"Download completed! ({format_size(os.path.getsize(file_path))})")

            # Upload to WebDAV (Assume functions are defined elsewhere)
            webdav_url, username, password = get_credintials()
            save_name = os.path.basename(file_path)
            asyncio.create_task(upload_to_nextcloud_webdav(update, context, webdav_url, file_path, username, password, save_name))

    except aiohttp.ClientError as e:
        await status_msg.edit_text(f"Download failed: {str(e)}")
    except Exception as e:
        await status_msg.edit_text(f"An error occurred: {str(e)}")

async def upload_to_nextcloud_webdav(update: Update, context: ContextTypes.DEFAULT_TYPE,webdav_url, local_file_path, username, password, save_name) -> None:
    user_id = update.effective_user.id
    status_put_msg = await update.message.reply_text("Uploading...")
    headers = {'Content-Type': 'application/octet-stream'}
    try:
        with open(local_file_path, 'rb') as file:
            response = requests.put(f"{webdav_url}temp/{save_name}", data=file, headers=headers, auth=(username, password))
        if response.status_code in (200, 201, 204):
            await status_put_msg.edit_text(f"Upload successful!", parse_mode='Markdown')
            public_link = await get_public_share_link(webdav_url, username, password, save_name)
            if USER_DELETE_PREFERENCE[user_id] == 'yes':
                schedule_file_deletion(webdav_url, username, password, save_name, local_file_path)
            await status_put_msg.edit_text(f"🎉 Upload Successful! \n\n File name: `{save_name}`\n\n🔗 [Direct download]({public_link}) ({format_size(os.path.getsize(local_file_path))})\n_({'Valid for 30 mins' if USER_DELETE_PREFERENCE[user_id] == 'yes' else 'Auto Delete is off!'})_",parse_mode='Markdown')
            os.remove(local_file_path)
        else:
            await status_put_msg.edit_text(f"Failed to upload. Status code: {response.status_code}")
            print(f"Failed to upload. Status code: {response.status_code}\nResponse text: {response.text}")
            return "error"
    except Exception as err:
        await status_put_msg.edit_text(f"An error occurred during upload: {err}")
        print(f"An error occurred during upload: {err}")
        return "error"

async def ytdlp_sd_download(update: Update, context: CallbackContext, status_msg, file_url) -> None:
    
    user_id = update.message.from_user.id
    user_folder = Path(f'Files/{user_id}')
    user_folder.mkdir(parents=True, exist_ok=True)
    
    await status_msg.edit_text(f"Getting Video Details...", parse_mode='Markdown')

    try:
        ydl_opts = {
            'format': 'best',
            'quiet': True,
            'cookiefile': cookies_path,
            'extract_flat': True,  # This ensures only the URL is extracted
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(file_url, download=False)
            driect_download_link = info_dict.get('url')
            
            try:
                video_name = f"{clean_string(info_dict['title'][:60])}.{info_dict['ext']}"
            except KeyError:
                info_dict['title'] = "unknown_filename"
                video_name = f"{clean_string(info_dict['title'][:60])}.mp4"
            
            text2 = (
                "🎥 *Video Details* (SD)\n\n"
                f"**Name:** `{clean_string(info_dict['title'][:60])}`\n"
                f"**👁 Views:** {format_view_count(info_dict['view_count'])}\n"
                f"**📅 Uploaded on:** {get_time_ago(info_dict)}\n"
                f"**👤 Uploaded By:** {info_dict['uploader']}\n"
                f"**⏱ Duration:** {format_duration(info_dict['duration'])}"
            )
            try:
                await status_msg.edit_text(text2, parse_mode='Markdown')
            except:
                await status_msg.edit_text(text2)
    except Exception as e:
        await status_msg.edit_text(f"An Error Occured, Please Try again Later\n\nError: {e}", parse_mode='Markdown')
        return

    # Prepare user-specific download path
    user_id = update.effective_user.id
    user_folder = Path(f'Files/{user_id}')
    user_folder.mkdir(parents=True, exist_ok=True)

    # Notify user about download start
    status_msg = await update.message.reply_text("Starting download...")

    # Run the download in the background
    asyncio.create_task(yt_background_download(update, context, status_msg, user_folder, driect_download_link,video_name))

async def ytdlp_hd_download(update: Update, context: CallbackContext, status_msg, file_url) -> None:
    user_id = update.message.from_user.id
    user_folder = Path(f'Files/{user_id}')
    user_folder.mkdir(parents=True, exist_ok=True)
    
    await status_msg.edit_text(f"Getting Video Details...", parse_mode='Markdown')

    ydl_opts = {
        'format': 'best',
        'quiet': True,
        'cookiefile': cookies_path,
        'extract_flat': True,  # This ensures only the URL is extracted
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(file_url, download=False)
            video_name = f"{clean_string(info_dict['title'][:60])}.{info_dict['ext']}"
            text2 = (
                "🎥 *Video Details* (HD)\n\n"
                f"**Name:** `{clean_string(info_dict['title'][:60])}`\n"
                f"**👁 Views:** {format_view_count(info_dict['view_count'])}\n"
                f"**📅 Uploaded on:** {get_time_ago(info_dict)}\n"
                f"**👤 Uploaded By:** {info_dict['uploader']}\n"
                f"**⏱ Duration:** {format_duration(info_dict['duration'])}"
            )
            try:
                await status_msg.edit_text(text2, parse_mode='Markdown')
            except:
                await status_msg.edit_text(text2)
        status_msg = await update.message.reply_text("Starting download...")
    except:
        await status_msg.edit_text(f"Oops! There was an error fetching the video details...",parse_mode='Markdown')
        time.sleep(0.5)
        status_msg = await update.message.reply_text("🔄 Attempting to download the video directly...")


    start_temp_time = time.time()
    progress_output = ""
    try:
        output_path = str(user_folder / f"{clean_string(info_dict['title'][:60])}.%(ext)s")  # This will save with the video title and extension
    except KeyError:
        info_dict['title'] = "unknown_filename"
        output_path = str(user_folder / f"{clean_string(info_dict['title'][:60])}.%(ext)s")


    process = subprocess.Popen(
        ['yt-dlp', '--cookies', cookies_path, '-o', output_path, file_url],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1  # Line-buffered
    )
    
    # Print logs line by line with improved formatting and emojis
    for line in process.stdout:
        if ("Extracting URL" in line.strip()) or (line.strip().startswith("[youtube]")):
            continue
        if not line.strip().startswith("[download]"):
            progress_output += line.strip() + "\n"
        current_time = time.time()
        elapsed_time = current_time - start_temp_time
        if elapsed_time >= 0.5:
            start_temp_time = current_time
            try:
                await status_msg.edit_text(f"🚀 **Progress Update:**\n{progress_output + line.strip()} 📥", parse_mode='Markdown')
            except:
                continue

    for line in process.stderr:
        print(f"❌ ERROR: {line.strip()} ⚠️")

    for filename in os.listdir(user_folder):
        if filename.startswith(clean_string(info_dict['title'][:10])):
            save_name = filename
            file_path = os.path.join(user_folder, filename)

    #await status_msg.edit_text("✅ **Download Completed!**", parse_mode='Markdown') ({format_size(os.path.getsize(file_path))})
    await status_msg.edit_text(f"✅ **Download Completed!** ({format_size(os.path.getsize(file_path))})", parse_mode='Markdown')

    # Upload to WebDAV (Assume functions are defined elsewhere)
    webdav_url, username, password = get_credintials()
    asyncio.create_task(upload_to_nextcloud_webdav(update, context, webdav_url, file_path, username, password, save_name))
    
async def yt_background_download(update: Update, context: CallbackContext, status_msg, user_folder: Path, file_url: str, file_name, attemptNumber=1) -> None:
    """Performs the download in the background and updates the user about the progress."""
    # File size limit in bytes (4GB)
    MAX_FILE_SIZE = 4 * 1024 * 1024 * 1024

    try:
        # Send a HEAD request to get file metadata
        async with aiohttp.ClientSession() as session:
            async with session.head(file_url) as head_resp:
                if head_resp.status!= 200:
                    if attemptNumber > 3:
                        await status_msg.edit_text(f"Failed to access file. Status code: {head_resp.status}\n🔄 Attempting failed! (Attempt No: {attemptNumber-1}) | Attempt number reached its maximum limit!")
                        return 
                    await status_msg.edit_text(f"Failed to access file. Status code: {head_resp.status}\n🔄 Re-attempting (Attempt No: {attemptNumber})")
                    time.sleep(1)
                    return await yt_background_download(update, context, status_msg, user_folder, file_url, file_name, attemptNumber + 1)

                # Check file size before downloading
                content_length = head_resp.headers.get('Content-Length')
                if content_length and int(content_length) > MAX_FILE_SIZE:
                    await status_msg.edit_text(f"File is too large to download (limit: {MAX_FILE_SIZE / (1024 ** 3)}GB).")
                    return

            # Proceed with the download
            file_path = user_folder / file_name
            async with aiohttp.ClientSession() as session:
                async with session.get(file_url) as resp:
                    if resp.status!= 200:
                        await status_msg.edit_text(f"Failed to download file. Status code: {resp.status}")
                        return

                    with open(file_path, 'wb') as file:
                        downloaded = 0
                        content_length = int(content_length) if content_length else None
                        last_reported_percentage = 0
                        last_update_time = asyncio.get_running_loop().time()
                        xc = True

                        # Download in chunks
                        async for chunk in resp.content.iter_chunked(8192):
                            file.write(chunk)
                            downloaded += len(chunk)

                            # Report download progress every 2 seconds
                            current_time = asyncio.get_running_loop().time()
                            if content_length and current_time - last_update_time >= 0.5:
                                percentage = (downloaded / content_length) * 100
                                bar_length = 15  # Length of the progress bar 
                                filled_length = int(bar_length * downloaded // content_length)
                                bar = '■' * filled_length + '□' * (bar_length - filled_length)
                                try:
                                    await status_msg.edit_text(
                                        f"Downaloding...\n⬇️ |{bar}| {percentage:.2f}% ({format_size(content_length)})"
                                    )
                                except:
                                    pass
                                last_update_time = current_time
                            else:
                                if xc:
                                    if content_length:
                                        await status_msg.edit_text(f"Downloading...")
                                    else:
                                        await status_msg.edit_text(f"Downloading... (Unknown File Size)")
                                    xc = False


            # Notify user of successful download
            await status_msg.edit_text(f"✅ **Download Completed!** ({format_size(os.path.getsize(file_path))})", parse_mode='Markdown')
            #await status_msg.edit_text(f"Download completed! ({format_size(os.path.getsize(file_path))})")

            # Upload to WebDAV (Assume functions are defined elsewhere)
            webdav_url, username, password = get_credintials()
            save_name = os.path.basename(file_path)
            asyncio.create_task(upload_to_nextcloud_webdav(update, context, webdav_url, file_path, username, password, save_name))


    except aiohttp.ClientError as e:
        await status_msg.edit_text(f"Download failed: {str(e)}")
    except Exception as e:
        await status_msg.edit_text(f"An error occurred: {str(e)}")

# ___________________________________________________________ MAIN CODE __________________________________________________________________
user_links = dict()

def get_credintials():
    webdav_url = "https://oto.lv.tab.digital/remote.php/dav/files/amharnisfer072%40gmail.com/"
    username = "amharnisfer072@gmail.com" 
    password = "Aharmax123"
    return webdav_url, username, password

async def start_command(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(f'Welcome to AZ Downloader Bot!')

async def settings_command(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if not USER_DELETE_PREFERENCE.get(user_id):  
        USER_DELETE_PREFERENCE[user_id] = "yes"
    await update.message.reply_text(
        f"Auto Delete in 30 mins: *{'ON' if USER_DELETE_PREFERENCE[user_id] == 'yes' else 'OFF'}*\n\n"
        "*Commands*\n\n"
        "_/storage_\n - Check Storage\n"
        "_/clearmyspace_\n - Clear my storage space\n"
        "_/clearall (for Admins)_\n - Clear entire space\n"
        "_/turnOff | /turnOn AutoDelete_\n - Change Auto Delete Preference", 
        parse_mode='Markdown'
    )

async def normal_download_command(update: Update, context: CallbackContext) -> None:
    if update.message.text.strip() == "/dl":
        await update.message.reply_text("Please send the link in the format:\n/dl <link>")
        return
    direct_link = update.message.text.split("dl ")[-1]
    user_id = update.effective_user.id
    user_folder = Path(f'Files/{user_id}')
    user_folder.mkdir(parents=True, exist_ok=True)
    if not USER_DELETE_PREFERENCE.get(user_id):  
        USER_DELETE_PREFERENCE[user_id] = "yes"
    status_msg = await update.message.reply_text("Starting download...")
    asyncio.create_task(background_download(update, context, status_msg, user_folder, direct_link, 1))

async def yt_sd_download_command(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if not USER_DELETE_PREFERENCE.get(user_id):  
        USER_DELETE_PREFERENCE[user_id] = "yes"
    status_msg = await update.message.reply_text("Looking...")
    if update.message.text.strip() == "/ysd":
        await update.message.reply_text("Please send the link in the format:\n/ysd <link>")
        return
    
    # Extract the link from the command
    command_parts = update.message.text.split(" ", 1)
    if len(command_parts) < 2:
        await update.message.reply_text("Error: No link provided. Use the format:\n/ysd <link>")
        return
    
    file_url = command_parts[1].strip()
    asyncio.create_task(ytdlp_sd_download(update, context, status_msg, file_url))

async def yt_hd_download_command(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if not USER_DELETE_PREFERENCE.get(user_id):  
        USER_DELETE_PREFERENCE[user_id] = "yes"
    status_msg = await update.message.reply_text("Looking...")
    if update.message.text.strip() == "/yhd":
        await update.message.reply_text("Please send the link in the format:\n/yhd <link>")
        return
    
    # Extract the link from the command
    command_parts = update.message.text.split(" ", 1)
    if len(command_parts) < 2:
        await update.message.reply_text("Error: No link provided. Use the format:\n/yhd <link>")
        return
    
    file_url = command_parts[1].strip()
    asyncio.create_task(ytdlp_hd_download(update, context, status_msg, file_url))

async def storage_command(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(f"Storage used: {format_size(get_folder_size('Files'))}")

async def clearmyspace_command(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text(f"{clear_folder(f'Files/{user_id}')}")

async def clearall_command(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if str(user_id) in ADMIN_IDs:
        await update.message.reply_text(f"Full 'Files' Folder Clearing!\n{clear_folder(f'Files')}")
    else:
        await update.message.reply_text(f"This is an ADMIN command!")

async def serverStorage_command(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if str(user_id) in ADMIN_IDs:
        webdav_url, username, password = get_credintials()
        check_nextcloud_storage(webdav_url, username, password)
    else:
        await update.message.reply_text(f"This is an ADMIN command!")

async def turnOff_command(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if not USER_DELETE_PREFERENCE.get(user_id):  
        USER_DELETE_PREFERENCE[user_id] = "yes"
    USER_DELETE_PREFERENCE[user_id] = "no"
    await update.message.reply_text(f"You have turned off Auto Delete!\nFile will remain in servers unless Admins delete them.")
    
async def turnOn_command(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if not USER_DELETE_PREFERENCE.get(user_id):  
        USER_DELETE_PREFERENCE[user_id] = "yes"
    USER_DELETE_PREFERENCE[user_id] = "yes"
    await update.message.reply_text(f"You have turned on Auto Delete!\nFile will be deleted in 30 mins.")

async def echo(update: Update, context: CallbackContext) -> None:
    user_message = update.message.text
    user_id = update.effective_user.id
    if not USER_DELETE_PREFERENCE.get(user_id):  
        USER_DELETE_PREFERENCE[user_id] = "yes"
    return_text = await handle_message(update, context, user_message, user_id)
    if return_text != "":
        await update.message.reply_text(return_text)

async def set_bot_commands(application):
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("dl", "Direct download Using Requests & Upload"),
        BotCommand("ysd", "yt SD Download & Upload"),
        BotCommand("yhd", "yt HD Download & Upload"),
        BotCommand("settings", "Settings"),
    ]
    await application.bot.set_my_commands(commands)

def main():
    application = Application.builder().token(API_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("dl", normal_download_command))
    application.add_handler(CommandHandler("ysd", yt_sd_download_command))
    application.add_handler(CommandHandler("yhd", yt_hd_download_command))
    application.add_handler(CommandHandler("storage", storage_command))
    application.add_handler(CommandHandler("clearmyspace", clearmyspace_command))
    application.add_handler(CommandHandler("clearall", clearall_command))
    application.add_handler(CommandHandler("turnOff", turnOff_command))
    application.add_handler(CommandHandler("turnOn", turnOn_command))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    application.job_queue.run_once(set_bot_commands, when=0)
    application.run_polling()

if __name__ == '__main__':
    print("AZ Downloader Bot running...")
    main()
