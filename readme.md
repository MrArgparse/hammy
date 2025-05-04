**Features:**

-Sends links to clipboard

-Upload images from the command line or your context menu

-Usable as library for your own scripts

-Outputs to text files

-Supports for both urls and files

-Supports resizing and will offer to resize instead of throwing error if size is too big

-Can format into imgnm as well which is not available on the site

-May add certain options later like the NSFW switch (is it of any use?), album_id, category_id and expiration

-For direct links just omit any format switches, if a folder is specified, all image files will be uploaded recursively.

-An example with 4 items

**Install:**

``pip install git+https://github.com/MrArgparse/hammy.git``

-Run the tool for the first time by entering ``hammy`` in the terminal

-Open config file located in %LOCALAPPDATA%\hammy\hammy_config.json and enter your api_key in the appropriate section.

**Usage instructions**

``hammy x.jpg /folder x2.jpg https://hamster.is/image.png``

Sends links to clipboard
    
``--clip``, ``-c``

Output links in bbcode format
    
``--format``, ``-b``

Output links in bbthumbs format

``--format``, ``-h``

Output links in imgnm format

``--format``, ``-i``

Output links in medium format

``--format``, ``-m``

Output links in thumbs format

``--format``, ``-t``

Output links in medium format

``--format``, ``-m``

Output links in medium thumbs format

``--format``, ``-u``

Output links on a single line

``--single``, ``-s``

Resize images to desired width value in pixels

``--width``, ``-w``

