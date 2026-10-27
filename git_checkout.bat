git config --global user.name "Bill Wang"
git config --global user.email "516545865@qq.com"

git add .
git commit -m "push to github."

git branch -M main
git remote add origin  "https://github.com/yourusername/yourrepository.git"
git push -u origin main
