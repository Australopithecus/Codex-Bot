import tkinter as tk

root = tk.Tk()
root.title("Tk Sanity")
root.geometry("400x200")
root.configure(bg="#f8fafc")

label = tk.Label(root, text="If you can see this, Tk is rendering.", font=("Helvetica", 14), bg="#f8fafc", fg="#0f172a")
label.pack(expand=True)

root.mainloop()
