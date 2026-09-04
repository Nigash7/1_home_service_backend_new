"""
One way for every dashboard form to handle a file that is already on a record.

Before this, an edit form could only ever *add*: uploading nothing left the
old file in place and there was no way to say "there should be no image here".
Every form now offers the same three outcomes -- keep, replace, remove -- and
they all go through `apply_uploaded_file`, so a new form cannot quietly grow a
fourth behaviour.
"""


def apply_uploaded_file(request, obj, field_name, form_name=None):
    """
    Applies one file input from `request` to `obj.<field_name>`.

    A new upload replaces what is there. The "Remove" tick clears it. Neither
    leaves the record alone, which is what an admin editing some other field
    expects to happen to an image they never touched.

    `form_name` is for the rare field whose input is named something else;
    it defaults to the model field's own name.

    Returns True when the field changed, so a caller can tell whether there is
    anything to save.
    """
    name = form_name or field_name

    uploaded = request.FILES.get(name)
    if uploaded:
        setattr(obj, field_name, uploaded)
        return True

    if request.POST.get(f'{name}_clear') != 'on':
        return False

    current = getattr(obj, field_name, None)
    if not current:
        return False

    try:
        # Takes the file out of storage as well as off the record.
        current.delete(save=False)
    except Exception:
        # The reference is what the admin was actually asking about. A
        # storage that will not let go of the file -- a network blip, a
        # remote that has already lost it -- must not fail the whole save.
        pass

    setattr(obj, field_name, None)
    return True
