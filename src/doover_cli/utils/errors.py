# currently unused

# def on_error(self, exception):
#     if isinstance(exception, NotFound):
#         print(
#             "We couldn't find what you're looking for! Perhaps try a different Agent ID, or check your spelling?"
#         )
#
#     elif isinstance(exception, Forbidden):
#         print(
#             "Uh-oh - you don't have access to that. Perhaps try a different Agent ID, or ask for permissions?"
#         )
#
#     elif isinstance(exception, PermissionError):
#         print(
#             "Looks like you tried to do something to a file you don't have access to. Perhaps try with sudo?"
#         )
#
#     else:
#         print(
#             f"Hmm... something went wrong: {exception}\n\nPerhaps you can understand more than me?"
#         )
#
#     if not self.args.enable_traceback:
#         print("Try running with --enable-traceback flag to see the full error.")
#     else:
#         traceback.print_exc()
