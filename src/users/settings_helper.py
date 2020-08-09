"""A collection of useful functions for working with a users settings. We store
user settings in arango with no TTL. A users settings are fixed when created,
meaning that even if you never change your settings and we change the default,
your settings won't be affected.

The exception to this are ratelimits, because although their settings don't
change we have a boolean 'user-specific-ratelimit' which must be set to True
for a users ratelimit to be frozen. This is because our assumption is that
ratelimit changes will _generally_ be beneficial (i.e., reducing restrictions),
so freezing as a default probably won't be beneficial.
"""


VIEW_OTHERS_SETTINGS_PERMISSION = 'view-others-settings'
"""The permission required to view others settings"""

VIEW_SETTING_CHANGE_AUTHORS_PERMISSION = 'view-setting-change-authors'
"""The permission required to view change author usernames on settings
events. With this permission the user can see who modified their settings
if it wasn't them, without it they cannot see who modified their settings
if it wasn't them, although they will know it wasn't them."""

EDIT_OTHERS_STANDARD_SETTINGS_PERMISSION = 'edit-others-standard-settings'
"""The permission required to edit the standard settings on
someone elses behalf, e.g., request opt out."""

EDIT_RATELIMIT_SETTINGS_PERMISSION = 'edit-ratelimit-settings'
"""The permission required to edit ones own ratelimit settings.
"""

EDIT_OTHERS_RATELIMIT_SETTINGS_PERMISSION = 'edit-others-ratelimit-settings'
"""The permission required to edit ratelimit settings for other
people."""

ADD_SELF_AUTHENTICATION_METHODS_PERM = 'add-self-authentication-methods'
"""The permission required to add authentication methods to ones own
account"""

ADD_OTHERS_AUTHENTICATION_METHODS_PERM = 'add-others-authentication-methods'
"""The permission required to add authentication methods to others accounts"""
