# Source: <https://wiki.aaps.app/en/latest/SettingUpAaps/BrowserBuild.html>

# Browser build

Building AAPS with GitHub Actions.
Minimum AAPS version supported is 3.3.2.1.

## Build yourself instead of download

The AAPS app (an apk file) is not available for download, due to regulations around medical devices. It is legal to build the app for your own use, but you must not give a copy to others!
See  FAQ page for details.

## Device and software specifications for building AAPS

We recommend using an Android device. You can also use a computer or an iOS device.
You will need to use multiple tabs in your browser, and switch from one to the other. Example Chrome:
You also need a Google account so that the app can be saved in your Google Drive.
Note
This wiki assumes you’re performing all operations with your cellular phone and the Chrome web browser.
 You will need to jump from tab to tab: start with all tabs closed to avoid losing yourself when switching from one to another.

## 1. AAPS personal fork

You will need to secretly store your personal Android Java Key and Google Drive information in GitHub (later in the process, we will explain how).
Since this cannot be done inside the public repository of AndroidAPS, you need to make your personal copy of the source code (called a fork).

### GitHub account

You need to  create a GitHub account if you don’t have one yet.
 You can sign up with your email, or you can sign up with Google. Follow the registration and verification process.
When you have an account,  sign in to GitHub .

### Fork AndroidAPS

Open the official AndroidAPS repository following  this link .
Tap on the fork icon. This will create a copy inside your own account.
Scroll down the next screen and tap  Create Fork .
Note: you can  unselect “Copy the main branch only” if you will want to build developers versions or customizations.
Note
You cannot fork and you see this?
Create a new fork
A fork is a copy of a repository. Forking a repository allows you to freely experiment with changes without affecting the original project. View existing forks.
Required fields are marked with an asterisk (*).
No available destinations to fork this repository.
 This means you already have an existing fork of AndroidAPS.
 Make sure it’s up to date and continue to Preparation Steps.
Warning
Never delete your fork without having done a backup of your secrets!
GitHub now displays your personal copy of AndroidAPS. Leave this web browser tab open.

## 2. Preparation Steps

- If you are building from an Android device, install  File Manager Plus from the Google Play store.
File Manager Plus
Install  File Manager Plus from the Google Play store.
The app is necessary for the preliminary phase and you can safely delete it from your phone once you’ve successfully build and installed AAPS.
Check this is the correct app and tap Install, then Open.
Tap Next to accept the Privacy Policy.
Tap Next to allow the app to access the phone files.
Switch to enable access to all files.
Allow File Manager + notifications.
Consent to profiling.
- Download the preparation file from here:  aaps-ci-preparation.html
Note
- If you open this page from within an app (via a web view), the HTML file may not download. Please copy the URL and open it in your browser instead:
<https://github.com/nightscout/aaps-ci-preparation/releases/download/release-v1.1.2/aaps-ci-preparation.html>
Or visit the latest release page:
<https://github.com/nightscout/aaps-ci-preparation/releases/latest>
2.Backup copy hosted on this site:
- If the external link is also unavailable, you can use this backup file to download.
 aaps-ci-preparation.html
AndroidAPS build requires private keys, that are stored in a Java KeyStore (JKS):
- If this is your first time building AAPS (or you don’t have a an Android Studio JKS), follow  AAPS-CI Option 1 – Generate JKS to complete the setup.
Warning
Building AAPS with  Option 1 will not allow you to upgrade your existing AAPS. You will need to:
- Export settings on your phone.
- Copy or upload the settings file from your phone to an external location (i.e. your computer, cloud storage service…).
- Generate a new version of the signed apk as described in Option 1 and transfer it to your phone.
- Uninstall previous AAPS version on your phone.
- Install new AAPS version on your phone.
- Import settings to restore your objectives and configuration.
- Restore your data from Nightscout.
- If you want to use your own JKS (the one you used on a previous build of AAPS from a computer in Android Studio), you know its password and alias (key0), please choose  AAPS-CI Option 2 – Upload Existing JKS .
The AAPS app will be saved in your Google Cloud drive once built.

### AAPS-CI Option 1 – Generate JKS

- Suitable for first-time users, or those without a JKS, or who have forgotten the password or alias.
- Here are examples using multiple platforms below.
- Select your platform in the list below, between Android (preferred choice), iOS or Computer.
 Android
Compatible with Android (The simplest, recommended as the first choice)
 Wiki

### Open the CI preparation help file

With File Manager+, open the file  aaps-ci-preparation-html you downloaded above.
Select Downloads.
And search for this file, tap it to open it, open it with Chrome, tap Just once.
It will open like this.
Select Generate JKS. The field below will populate with characters.
Keep this tab open.

### Create a new secret in GitHub

Return to your GitHub browser tab: your own AndroidAPS copy.

- Top right, tap the  ... button
- Select Settings in the list
Scroll down to Security and select Secrets and variables.
Now select Actions
Scroll down to Repository secrets and tap New repository secret
You will see this dialog (scroll down if it’s not visible).
Leave the tab opened like this.
Switch to the File Explorer Plus tab.
Tap the top Copy button.
Switch back to the GitHub tab.
In the Name field, paste the text you just copied. Use a long touch on the text box to show the paste menu.
Switch to the File Explorer Plus tab.
Tap the second Copy button.
Switch back to the GitHub tab.
- In the Secret field, paste the text you just copied. Use a long touch on the text box to show the paste menu.
- Tap Add secret.
Check the secret has been added, scroll down to verify.
 Video
 iOS
Compatible with iOS (using iPad as an example)
 Computer
Use a computer (supports Windows/Mac/Linux)
Open the webpage  <https://simplewebserver.org/download.html>
Install Simple HTTP Server
 If you are a Windows/Mac user, you can install it from the store.
 After clicking the link, you will be asked whether to allow opening it. Please choose Open Link.
Example on Mac:
- get → install → open
- Click Get Started
- Click Get Server
- In Folder Path, select the folder where aaps-ci-preparation.html is located, and then click Create Server.
- Seeing this screen means the server has been started.
- Do not close Simple HTTP Server. Please switch to your browser and open
<http://127.0.0.1:8080/aaps-ci-preparation.html>
- For the subsequent steps, please refer to the video below, starting from 1 minute 37 seconds.
Skip the next section and continue  here .
---### AAPS-CI Option 2 – Upload Existing JKS
- Suitable for users who already have a JKS and know the JKS password and alias (For  KEYSTORE_PASSWORD ,  KEY_ALIAS , and  KEY_PASSWORD , enter your actual password and alias in GitHub - those from Android Studio, see below where you used them.)
KEY + PASSWORDS
- Here are examples using multiple platforms below.
- Select your platform in the list below, between Android (preferred choice) or Computer.
 Android
Compatible with Android (The simplest, recommended as the first choice)
 Wiki

### Copy your Android Studio key in your Google Cloud drive

On your computer, search for the keystore file you used to build AAPS. It is named with the extension  .jks .
Drag it into  your Google Drive , either inside the browser or your mapped Google Drive.
Open File Manager Plus and select Cloud.
Add a Cloud location.
Choose Google Drive.
Select your Google Drive account email. Tap OK.
Your Google Cloud drive should display its contents. Now return to the app home page.

### Open the CI preparation help file

Open the file  aaps-ci-preparation-html you downloaded above.
Select Downloads.
And search for this file, tap it to open it, open it with Chrome, tap Just once.
It will open like this.
Scroll down to Option 2: Upload Existing JKS. Expand the interface.
Select Choose File.
Pick your KeyStore file from your Google Drive files.
The field below will populate.
Keep this tab open.

### Create a new secret in GitHub

Return to your GitHub browser tab: your own AndroidAPS copy.

- Top right, tap the  ... button
- Select Settings in the list
Scroll down to Security and select Secrets and variables.
Now select Actions
Scroll down to Repository secrets and tap New repository secret
You will see this dialog (scroll down if it’s not visible).
Leave the tab opened like this.
Switch to the File Explorer Plus tab.
Tap the top Copy button.
Switch back to the GitHub tab.
In the Name field, paste the text you just copied. Use a long touch on the text box to show the paste menu.
Switch to the File Explorer Plus tab.
Tap the second Copy button.
Switch back to the GitHub tab.
- In the Secret field, paste the text you just copied. Use a long touch on the text box to show the paste menu.
- Tap Add secret.
Check the secret has been added, scroll down to verify.
Add a new secret: tap the New repository secret button.
Switch to the File Explorer Plus tab.
Tap the top Copy button to copy  KEYSTORE_PASSWORD .
Note: if you’re comfortable with typing the key names directly in GitHub you don’t need to Copy/Paste. If you’re not sure you will type exactly the same key name, continue like this. Note that you shouldn’t leave  : at the end of the key name.
Switch back to the GitHub tab.
- Paste the new key name.
- In the Secret entry, put your KeyStore password (don’t leave it empty).
- Tap Add secret.
Check the secret has been added, scroll down to verify.
Tap the New repository secret button shown above.
Switch to the File Explorer Plus tab.
Tap the top Copy button to copy  KEYSTORE_ALIAS .
Switch back to the GitHub tab.
- Paste the new key name.
- In the Secret entry, put your KeyStore Alias (usually it’s  key0 , lowercase with the number zero, not the letter O). Don’t let Android autocorrect it.
- Tap Add secret.
Check the secret has been added, scroll down to verify.
Tap the New repository secret button shown above.
Switch to the File Explorer Plus tab.
Tap the top Copy button to copy  KEY_PASSWORD .
Switch back to the GitHub tab.
- Paste the new key name.
- In the Secret entry, put your Key password (don’t leave it empty). It is usually the same than your KeyStore password.
- Tap Add secret.
Check the secret has been added, scroll down to verify.
 Video
 Computer
Use a computer (supports Windows/Mac/Linux)
Install Simple HTTP Server
 If you are a Windows/Mac user, you can install it from the store. After clicking the link, you will be asked whether to allow opening it. Please choose Open Link.
Example on Mac:
- get → install → open
- Click Get Started
- Click Get Server
- In Folder Path, select the folder where aaps-ci-preparation.html is located, and then click Create Server.
- Seeing this screen means the server has been started.
- Do not close Simple HTTP Server. Please switch to your browser and open
<http://127.0.0.1:8080/aaps-ci-preparation.html>
- For the subsequent steps, please refer to the video below, starting from 2 minute 18 seconds.

### AAPS-CI Google Drive Auth

Warning
No matter which of the prior sets of instructions you followed (option 1 or option 2), you MUST add the Google Drive authorization to successfully use the Browser Build.
Note: If you already followed this part in the video, you can now skip to  here .
Return to the File Explorer Plus tab.
Scroll down to the Google Drive Auth section and tap Start Auth.
Select your Google account.
Scroll down and accept the access. The web page needs it to obtain the Google Drive authentication key.
Tap Continue.
The  GDRIVE_OAUTH2 field will populate, tap the top Copy button.
Switch back to the GitHub tab.
Scroll down to Repository secrets and tap New repository secret.
If you followed Option 1 you should see this:
If you followed Option 2 there will be more keys:
In the Name field, paste the text you just copied. Use a long touch on the text box to show the paste menu.
Switch to the File Explorer Plus tab.
Tap the second Copy button.
Switch back to the GitHub tab.

- In the Secret field, paste the text you just copied. Use a long touch on the text box to show the paste menu.
- Tap Add secret.
You should have either two (option 1) or five (option 2) secrets entries now.
GitHub will now be able to store the AAPS apk file in your Google Drive, once built.

## AAPS-CI GitHub Actions to Build the AAPS APK

- Suitable for general users.
 Wiki

### Run the Workflow to Build the Signed APK

- In your GitHub copy of AndroidAPS, select Actions.
- Expand All Workflows.
- Select AAPS-CI
- Scroll down and tap Run Workflow.
- Select the branch you want to deploy (master), the  variant (fullRelease) and tap Run Workflow.
- You will see the message Workflow run was successfully requested. Refresh your browser page and you will be able to monitor the build progress. When the action completes, the AAPS CI action will show a green tick mark. You have successfully built the updated version of Android APS.

### Install the AAPS APK

- Open your Google Drive
- Browse into AAPS, select the new version folder and you will find both the phone and Android Wear versions.
 Video

### Build Version selection

Only AAPS versions from 3.3.2.1 and above will build with the Browser method.

### Build Variants selection

Note: both Android and Android Wear apps will be built automatically.

- Select the variant you need:
- fullRelease: For regular pump usage with full functionality.
- aapsclientRelease, aapsclient2Release : For caregivers (requires  Nightscout )。
- pumpcontrolRelease: To replace your pump app/controller
Variants ending with “Debug” indicates that the APK will be built in debug mode, which is useful for developers for troubleshooting.

## AAPS-CI Troubleshooting

### aaps-ci-preparation web page

- When you open aaps-ci-preparation.html using a file manager, it will start a temporary local server on your phone to display the webpage and receive the Google refresh token.
- If you see the screen below, it means you have been inactive for a while, and the file manager has already shut down the local server.
- Please reopen aaps-ci-preparation.html using the file manager app and complete the remaining steps.

### Google Refresh Token Expired

- Google OAuth2 refresh tokens will expire if not used for 6 months, and may also become invalid under other conditions (e.g., you have changed your Google account password, or manually revoked access). For more details, see the  Google OAuth2 documentation .
- You will see an error indicating that the access token is invalid, as shown below:
- If your build fails due to an expired or revoked Google refresh token, you will need to redo the  Google Drive Auth steps to obtain a new  GDRIVE_OAUTH2 token and update the secret in your GitHub repository, then re-run the build workflow.

### Disable Software That May Interfere With OAUTH Verification

- Disable any VPN or security app (firewall, antimalware,…) on the phone before trying to get the OAUTH key.

### Check GitHub Actions Permission Settings

- Make sure GitHub Actions policies are set to “Allow all actions and reusable workflows” (Settings → Actions → General).
actions/checkout@v4 and  actions/setup-java@v4 are not allowed to be used in  xxxxx/AndroidAPS . Actions in this workflow must be: within a repository owned by  xxxxx
---Warning
Customizations are usually not necessary. This is for your information ony.

## If you want to add a specific commit to your branch, please use cherry-pick

- Use workflow from Branch: Please enter the branch name you want to cherry-pick to.
- Upstream Repository: Please enter the repository name you want to cherry-pick from.
- Commit SHA: Please enter the commit SHA you want to cherry-pick.(like git commit hash)
- Select Build Variant:  variant

## CI KeyStore Export

If you want to export your stored keystore, use this method.
This script will export your previously configured keystore information (from Option 1 or Option 2) as a password-protected ZIP file to the  /AAPS/KeyStore directory in your Google Drive.
Warning
Before using this export method, make sure your keystore and Google Drive settings have been completed.

### Steps

- Add ZIP Password Secret:
- Go to your repository’s  Settings →  Secrets and variables →  Actions
- Click  New repository secret
- In the  Name field, enter:  ZIP_PASSWORD
- In the  Secret field, enter your custom ZIP encryption password
- Use only English letters and numbers for the password (no special symbols)
- Click  Add secret
- Run Export Workflow:
- Go to the  Actions tab in your repository
- Select  CI KeyStore Export
- Click  Run workflow
- The exported keystore ZIP file will be saved to your Google Drive
