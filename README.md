# This utility downloads an entire Pearson E-Book in a PDF format for a better viewing experience

The need for this utility came out of regularly wanting to read the E-Book for my Physics textbook
in places where I would have little to no internet, or where the internet would cut out randomly.

Not to mention that the E-Book sometimes doesn't even load, leading to an inability to even use the book in the first place!

# Using this utility

To use this utility, first log into the pearson website and access the E-Book. Then copy the url of the book *after* roughly 10 seconds (it should now contain multiple GET parameters). This url is the only argument to this utility.

Then, run this utility as follows:

    python3 downloader.py <url you copied>

Where python3 points to the location of a python interpreter with the PyPDF2 module available (`pip install pypdf2`)

This will take a few minutes, downloading each individual page of the PDF (thanks, Pearson, for using *individual* pdf files for each page a thousand page book!) to a temporary directory, then merging them into a final PDF.

The output pdf will be saved into the current directory as `out.pdf`
