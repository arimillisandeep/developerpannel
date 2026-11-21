"""Project templates for the "New project" wizard. Each template is a set of real files.

verified=True  -> this exact template was installed/built/run during development (see scripts/verify_templates.py)
verified=False -> the files follow the framework's standard layout but were NOT test-run, because the
                  toolchain (.NET, PHP, Flutter, Maven) was not available where this was built.
needs: what must exist to run it. "packages" means it needs package installation from the internet.
"""
GITIGNORE_NODE = "node_modules/\ndist/\n.env\n"
GITIGNORE_PY = "__pycache__/\n.venv/\n*.pyc\n.env\n"

VITE_REACT = {
    "package.json": '{\n  "name": "react-app",\n  "private": true,\n  "version": "0.1.0",\n  "type": "module",\n  "scripts": {\n    "dev": "vite --host 0.0.0.0",\n    "build": "vite build",\n    "preview": "vite preview --host 0.0.0.0"\n  },\n  "dependencies": {\n    "react": "^18.3.1",\n    "react-dom": "^18.3.1"\n  },\n  "devDependencies": {\n    "@vitejs/plugin-react": "^4.3.1",\n    "vite": "^5.4.0"\n  }\n}\n',
    "vite.config.js": "import { defineConfig } from 'vite';\nimport react from '@vitejs/plugin-react';\n\nexport default defineConfig({\n  plugins: [react()],\n  server: { port: 5173 },\n});\n",
    "index.html": '<!doctype html>\n<html lang="en">\n  <head>\n    <meta charset="UTF-8" />\n    <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n    <title>React app</title>\n  </head>\n  <body>\n    <div id="root"></div>\n    <script type="module" src="/src/main.jsx"></script>\n  </body>\n</html>\n',
    "src/main.jsx": "import React from 'react';\nimport { createRoot } from 'react-dom/client';\nimport App from './App.jsx';\nimport './index.css';\n\ncreateRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>);\n",
    "src/App.jsx": "import { useState } from 'react';\n\nexport default function App() {\n  const [count, setCount] = useState(0);\n  return (\n    <main>\n      <h1>Hello from WORKCODE</h1>\n      <button onClick={() => setCount(count + 1)}>Clicked {count} times</button>\n    </main>\n  );\n}\n",
    "src/index.css": "body {\n  font-family: system-ui, sans-serif;\n  margin: 2rem;\n}\n\nbutton {\n  padding: 0.5rem 1rem;\n}\n",
    ".gitignore": GITIGNORE_NODE,
    "README.md": "# React app (Vite)\n\n```\nnpm install\nnpm run dev\n```\n",
}

EXPRESS = {
    "package.json": '{\n  "name": "express-api",\n  "private": true,\n  "version": "0.1.0",\n  "main": "src/server.js",\n  "scripts": {\n    "start": "node src/server.js",\n    "dev": "node --watch src/server.js"\n  },\n  "dependencies": {\n    "express": "^4.19.2"\n  }\n}\n',
    "src/server.js": "const express = require('express');\nconst itemsRouter = require('./routes/items');\n\nconst app = express();\napp.use(express.json());\n\napp.get('/api/health', (req, res) => res.json({ status: 'ok' }));\napp.use('/api/items', itemsRouter);\n\napp.use((req, res) => res.status(404).json({ error: 'Not found' }));\n\nconst port = process.env.PORT || 3000;\napp.listen(port, '0.0.0.0', () => console.log(`API listening on port ${port}`));\n",
    "src/routes/items.js": "const express = require('express');\n\nconst router = express.Router();\nconst items = [{ id: 1, name: 'First item' }];\n\nrouter.get('/', (req, res) => res.json(items));\n\nrouter.post('/', (req, res) => {\n  if (!req.body || !req.body.name) return res.status(400).json({ error: 'name is required' });\n  const item = { id: items.length + 1, name: req.body.name };\n  items.push(item);\n  res.status(201).json(item);\n});\n\nmodule.exports = router;\n",
    ".env.example": "PORT=3000\n",
    ".gitignore": GITIGNORE_NODE,
    "README.md": "# Express API\n\n```\nnpm install\nnpm start\n```\n\nGET /api/health, GET /api/items, POST /api/items {\"name\": \"...\"}\n",
}


def _prefix(folder, files):
    return {f"{folder}/{k}": v for k, v in files.items()}


TEMPLATES = [
    {"id": "html", "name": "HTML / CSS / JavaScript", "group": "Frontend", "verified": True, "needs": "Nothing. Opens in the Preview panel.",
     "open": "index.html", "files": {
        "index.html": '<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n  <title>My page</title>\n  <link rel="stylesheet" href="css/style.css">\n</head>\n<body>\n  <main>\n    <h1>Hello from WORKCODE</h1>\n    <button id="btn">Click me</button>\n    <p id="out"></p>\n  </main>\n  <script src="js/app.js"></script>\n</body>\n</html>\n',
        "css/style.css": "body {\n  font-family: system-ui, sans-serif;\n  margin: 2rem;\n}\n\nbutton {\n  padding: 0.5rem 1rem;\n  cursor: pointer;\n}\n",
        "js/app.js": "let clicks = 0;\n\ndocument.getElementById('btn').addEventListener('click', () => {\n  clicks += 1;\n  document.getElementById('out').textContent = `Clicked ${clicks} times`;\n  console.log('clicks', clicks);\n});\n",
        "README.md": "# Static website\n\nOpen index.html and use the Preview panel.\n"}},
    {"id": "react", "name": "React (Vite)", "group": "Frontend", "verified": True, "needs": "Node.js + packages (npm install).",
     "open": "src/App.jsx", "files": VITE_REACT},
    {"id": "vue", "name": "Vue 3 (Vite)", "group": "Frontend", "verified": True, "needs": "Node.js + packages (npm install).", "open": "src/App.vue", "files": {
        "package.json": '{\n  "name": "vue-app",\n  "private": true,\n  "version": "0.1.0",\n  "type": "module",\n  "scripts": {\n    "dev": "vite --host 0.0.0.0",\n    "build": "vite build"\n  },\n  "dependencies": {\n    "vue": "^3.4.0"\n  },\n  "devDependencies": {\n    "@vitejs/plugin-vue": "^5.1.0",\n    "vite": "^5.4.0"\n  }\n}\n',
        "vite.config.js": "import { defineConfig } from 'vite';\nimport vue from '@vitejs/plugin-vue';\n\nexport default defineConfig({ plugins: [vue()] });\n",
        "index.html": '<!doctype html>\n<html lang="en">\n  <head>\n    <meta charset="UTF-8" />\n    <title>Vue app</title>\n  </head>\n  <body>\n    <div id="app"></div>\n    <script type="module" src="/src/main.js"></script>\n  </body>\n</html>\n',
        "src/main.js": "import { createApp } from 'vue';\nimport App from './App.vue';\n\ncreateApp(App).mount('#app');\n",
        "src/App.vue": '<script setup>\nimport { ref } from \'vue\';\n\nconst count = ref(0);\n</script>\n\n<template>\n  <main>\n    <h1>Hello from WORKCODE</h1>\n    <button @click="count++">Clicked {{ count }} times</button>\n  </main>\n</template>\n',
        ".gitignore": GITIGNORE_NODE,
        "README.md": "# Vue app (Vite)\n\n```\nnpm install\nnpm run dev\n```\n"}},
    {"id": "node", "name": "Node.js", "group": "Backend", "verified": True, "needs": "Node.js.", "open": "index.js", "files": {
        "package.json": '{\n  "name": "node-app",\n  "private": true,\n  "version": "0.1.0",\n  "main": "index.js",\n  "scripts": {\n    "start": "node index.js",\n    "test": "node --test"\n  }\n}\n',
        "index.js": "const { greet } = require('./lib/greet');\n\nconsole.log(greet('WORKCODE'));\n",
        "lib/greet.js": "function greet(name) {\n  return `Hello from ${name}`;\n}\n\nmodule.exports = { greet };\n",
        "test/greet.test.js": "const test = require('node:test');\nconst assert = require('node:assert');\nconst { greet } = require('../lib/greet');\n\ntest('greet', () => {\n  assert.strictEqual(greet('A'), 'Hello from A');\n});\n",
        ".gitignore": GITIGNORE_NODE}},
    {"id": "express", "name": "Express API", "group": "Backend", "verified": True, "needs": "Node.js + packages (npm install).",
     "open": "src/server.js", "files": EXPRESS},
    {"id": "python", "name": "Python", "group": "Backend", "verified": True, "needs": "Python.", "open": "main.py", "files": {
        "main.py": 'from app.greet import greet\n\n\nif __name__ == "__main__":\n    print(greet("WORKCODE"))\n',
        "app/__init__.py": "",
        "app/greet.py": 'def greet(name: str) -> str:\n    return f"Hello from {name}"\n',
        "tests/test_greet.py": 'from app.greet import greet\n\n\ndef test_greet():\n    assert greet("A") == "Hello from A"\n',
        "requirements.txt": "pytest\n",
        ".gitignore": GITIGNORE_PY}},
    {"id": "flask", "name": "Flask", "group": "Backend", "verified": True, "needs": "Python + packages (pip install -r requirements.txt).", "open": "app.py", "files": {
        "app.py": 'from flask import Flask, jsonify, request\n\napp = Flask(__name__)\nitems = [{"id": 1, "name": "First item"}]\n\n\n@app.get("/api/health")\ndef health():\n    return jsonify(status="ok")\n\n\n@app.get("/api/items")\ndef list_items():\n    return jsonify(items)\n\n\n@app.post("/api/items")\ndef add_item():\n    data = request.get_json(silent=True) or {}\n    if not data.get("name"):\n        return jsonify(error="name is required"), 400\n    item = {"id": len(items) + 1, "name": data["name"]}\n    items.append(item)\n    return jsonify(item), 201\n\n\nif __name__ == "__main__":\n    app.run(host="0.0.0.0", port=5000)\n',
        "requirements.txt": "flask\n", ".gitignore": GITIGNORE_PY,
        "README.md": "# Flask API\n\n```\npip install -r requirements.txt\npython app.py\n```\n"}},
    {"id": "fastapi", "name": "FastAPI", "group": "Backend", "verified": True, "needs": "Python + packages (pip install -r requirements.txt).", "open": "main.py", "files": {
        "main.py": 'from fastapi import FastAPI, HTTPException\nfrom pydantic import BaseModel\n\napp = FastAPI(title="My API")\nitems = [{"id": 1, "name": "First item"}]\n\n\nclass ItemIn(BaseModel):\n    name: str\n\n\n@app.get("/api/health")\ndef health():\n    return {"status": "ok"}\n\n\n@app.get("/api/items")\ndef list_items():\n    return items\n\n\n@app.post("/api/items", status_code=201)\ndef add_item(body: ItemIn):\n    if not body.name.strip():\n        raise HTTPException(400, "name is required")\n    item = {"id": len(items) + 1, "name": body.name}\n    items.append(item)\n    return item\n',
        "requirements.txt": "fastapi\nuvicorn\n", ".gitignore": GITIGNORE_PY,
        "README.md": "# FastAPI\n\n```\npip install -r requirements.txt\nuvicorn main:app --host 0.0.0.0 --port 8000\n```\n"}},
    {"id": "django", "name": "Django", "group": "Backend", "verified": True, "needs": "Python + packages (pip install -r requirements.txt).", "open": "core/views.py", "files": {
        "manage.py": '#!/usr/bin/env python\nimport os\nimport sys\n\n\ndef main():\n    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")\n    from django.core.management import execute_from_command_line\n    execute_from_command_line(sys.argv)\n\n\nif __name__ == "__main__":\n    main()\n',
        "project/__init__.py": "",
        "project/settings.py": 'import os\nfrom pathlib import Path\n\nBASE_DIR = Path(__file__).resolve().parent.parent\nSECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")\nDEBUG = True\nALLOWED_HOSTS = ["*"]\n\nINSTALLED_APPS = [\n    "django.contrib.contenttypes",\n    "django.contrib.auth",\n    "core",\n]\nMIDDLEWARE = ["django.middleware.common.CommonMiddleware"]\nROOT_URLCONF = "project.urls"\nTEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True, "OPTIONS": {}}]\nDATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}\nDEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"\nUSE_TZ = True\n',
        "project/urls.py": 'from django.urls import path\n\nfrom core import views\n\nurlpatterns = [\n    path("", views.home),\n    path("api/health", views.health),\n]\n',
        "project/wsgi.py": 'import os\n\nfrom django.core.wsgi import get_wsgi_application\n\nos.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")\napplication = get_wsgi_application()\n',
        "core/__init__.py": "",
        "core/views.py": 'from django.http import HttpResponse, JsonResponse\n\n\ndef home(request):\n    return HttpResponse("<h1>Hello from WORKCODE</h1>")\n\n\ndef health(request):\n    return JsonResponse({"status": "ok"})\n',
        "requirements.txt": "django\n", ".gitignore": GITIGNORE_PY + "db.sqlite3\n",
        "README.md": "# Django\n\n```\npip install -r requirements.txt\npython manage.py runserver 0.0.0.0:8000\n```\n"}},
    {"id": "java", "name": "Java", "group": "Backend", "verified": True, "needs": "JDK 17+.", "open": "src/Main.java", "files": {
        "src/Main.java": 'public class Main {\n    public static void main(String[] args) {\n        System.out.println(Greeter.greet("WORKCODE"));\n    }\n}\n',
        "src/Greeter.java": 'public class Greeter {\n    public static String greet(String name) {\n        return "Hello from " + name;\n    }\n}\n',
        "README.md": "# Java\n\n```\njavac -d out src/*.java\njava -cp out Main\n```\n", ".gitignore": "out/\n*.class\n"}},
    {"id": "springboot", "name": "Spring Boot", "group": "Backend", "verified": False, "needs": "JDK 17+ and Maven + packages.", "open": "src/main/java/com/example/demo/HelloController.java", "files": {
        "pom.xml": '<?xml version="1.0" encoding="UTF-8"?>\n<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">\n  <modelVersion>4.0.0</modelVersion>\n  <parent>\n    <groupId>org.springframework.boot</groupId>\n    <artifactId>spring-boot-starter-parent</artifactId>\n    <version>3.3.2</version>\n    <relativePath/>\n  </parent>\n  <groupId>com.example</groupId>\n  <artifactId>demo</artifactId>\n  <version>0.0.1-SNAPSHOT</version>\n  <properties>\n    <java.version>17</java.version>\n  </properties>\n  <dependencies>\n    <dependency>\n      <groupId>org.springframework.boot</groupId>\n      <artifactId>spring-boot-starter-web</artifactId>\n    </dependency>\n    <dependency>\n      <groupId>org.springframework.boot</groupId>\n      <artifactId>spring-boot-starter-test</artifactId>\n      <scope>test</scope>\n    </dependency>\n  </dependencies>\n  <build>\n    <plugins>\n      <plugin>\n        <groupId>org.springframework.boot</groupId>\n        <artifactId>spring-boot-maven-plugin</artifactId>\n      </plugin>\n    </plugins>\n  </build>\n</project>\n',
        "src/main/java/com/example/demo/DemoApplication.java": 'package com.example.demo;\n\nimport org.springframework.boot.SpringApplication;\nimport org.springframework.boot.autoconfigure.SpringBootApplication;\n\n@SpringBootApplication\npublic class DemoApplication {\n    public static void main(String[] args) {\n        SpringApplication.run(DemoApplication.class, args);\n    }\n}\n',
        "src/main/java/com/example/demo/HelloController.java": 'package com.example.demo;\n\nimport java.util.Map;\n\nimport org.springframework.web.bind.annotation.GetMapping;\nimport org.springframework.web.bind.annotation.RestController;\n\n@RestController\npublic class HelloController {\n    @GetMapping("/api/health")\n    public Map<String, String> health() {\n        return Map.of("status", "ok");\n    }\n}\n',
        "src/main/resources/application.properties": "server.port=8080\n",
        "README.md": "# Spring Boot\n\n```\nmvn spring-boot:run\n```\n", ".gitignore": "target/\n"}},
    {"id": "csharp", "name": "C# console", "group": "Backend", "verified": False, "needs": ".NET SDK 8.", "open": "Program.cs", "files": {
        "App.csproj": '<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n    <OutputType>Exe</OutputType>\n    <TargetFramework>net8.0</TargetFramework>\n    <Nullable>enable</Nullable>\n    <ImplicitUsings>enable</ImplicitUsings>\n  </PropertyGroup>\n</Project>\n',
        "Program.cs": 'Console.WriteLine("Hello from WORKCODE");\n',
        "README.md": "# C# console\n\n```\ndotnet run\n```\n", ".gitignore": "bin/\nobj/\n"}},
    {"id": "aspnet", "name": "ASP.NET Core API", "group": "Backend", "verified": False, "needs": ".NET SDK 8.", "open": "Program.cs", "files": {
        "Api.csproj": '<Project Sdk="Microsoft.NET.Sdk.Web">\n  <PropertyGroup>\n    <TargetFramework>net8.0</TargetFramework>\n    <Nullable>enable</Nullable>\n    <ImplicitUsings>enable</ImplicitUsings>\n  </PropertyGroup>\n</Project>\n',
        "Program.cs": 'var builder = WebApplication.CreateBuilder(args);\nvar app = builder.Build();\n\nvar items = new List<Item> { new(1, "First item") };\n\napp.MapGet("/api/health", () => new { status = "ok" });\napp.MapGet("/api/items", () => items);\napp.MapPost("/api/items", (ItemIn body) =>\n{\n    var item = new Item(items.Count + 1, body.Name);\n    items.Add(item);\n    return Results.Created($"/api/items/{item.Id}", item);\n});\n\napp.Run("http://0.0.0.0:5000");\n\nrecord Item(int Id, string Name);\nrecord ItemIn(string Name);\n',
        "README.md": "# ASP.NET Core API\n\n```\ndotnet run\n```\n", ".gitignore": "bin/\nobj/\n"}},
    {"id": "php", "name": "PHP", "group": "Backend", "verified": False, "needs": "PHP 8.", "open": "public/index.php", "files": {
        "public/index.php": "<?php\nrequire __DIR__ . '/../src/greet.php';\n\n$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);\n\nif ($path === '/api/health') {\n    header('Content-Type: application/json');\n    echo json_encode(['status' => 'ok']);\n    exit;\n}\n\necho '<h1>' . htmlspecialchars(greet('WORKCODE')) . '</h1>';\n",
        "src/greet.php": "<?php\n\nfunction greet(string $name): string\n{\n    return \"Hello from {$name}\";\n}\n",
        "README.md": "# PHP\n\n```\nphp -S 0.0.0.0:8000 -t public\n```\n"}},
    {"id": "flutter", "name": "Flutter", "group": "Mobile", "verified": False,
     "needs": "Flutter SDK. This template has the Dart code only; run `flutter create .` once to generate the android/ios/web folders.",
     "open": "lib/main.dart", "files": {
        "pubspec.yaml": "name: workcode_app\ndescription: A Flutter app.\npublish_to: 'none'\nversion: 1.0.0+1\n\nenvironment:\n  sdk: '>=3.0.0 <4.0.0'\n\ndependencies:\n  flutter:\n    sdk: flutter\n\ndev_dependencies:\n  flutter_test:\n    sdk: flutter\n\nflutter:\n  uses-material-design: true\n",
        "lib/main.dart": "import 'package:flutter/material.dart';\n\nvoid main() => runApp(const MyApp());\n\nclass MyApp extends StatelessWidget {\n  const MyApp({super.key});\n\n  @override\n  Widget build(BuildContext context) {\n    return const MaterialApp(home: HomePage());\n  }\n}\n\nclass HomePage extends StatefulWidget {\n  const HomePage({super.key});\n\n  @override\n  State<HomePage> createState() => _HomePageState();\n}\n\nclass _HomePageState extends State<HomePage> {\n  int _count = 0;\n\n  @override\n  Widget build(BuildContext context) {\n    return Scaffold(\n      appBar: AppBar(title: const Text('WORKCODE')),\n      body: Center(child: Text('Clicked $_count times')),\n      floatingActionButton: FloatingActionButton(\n        onPressed: () => setState(() => _count++),\n        child: const Icon(Icons.add),\n      ),\n    );\n  }\n}\n",
        "test/widget_test.dart": "import 'package:flutter_test/flutter_test.dart';\nimport 'package:workcode_app/main.dart';\n\nvoid main() {\n  testWidgets('shows the counter', (tester) async {\n    await tester.pumpWidget(const MyApp());\n    expect(find.text('Clicked 0 times'), findsOneWidget);\n  });\n}\n",
        "README.md": "# Flutter\n\n```\nflutter create .\nflutter pub get\nflutter test\n```\n"}},
    {"id": "fullstack", "name": "Full-stack: React + Express", "group": "Full-stack", "verified": True,
     "needs": "Node.js + packages (npm install in client/ and server/).", "open": "client/src/App.jsx",
     "files": {
        **_prefix("server", EXPRESS),
        **_prefix("client", {**VITE_REACT,
            "vite.config.js": "import { defineConfig } from 'vite';\nimport react from '@vitejs/plugin-react';\n\n// /api calls go to the Express server\nexport default defineConfig({\n  plugins: [react()],\n  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:3000' } },\n});\n",
            "src/App.jsx": "import { useEffect, useState } from 'react';\n\nexport default function App() {\n  const [items, setItems] = useState([]);\n  const [name, setName] = useState('');\n  const [error, setError] = useState('');\n\n  const load = () => fetch('/api/items').then((r) => r.json()).then(setItems).catch(() => setError('API is not reachable'));\n  useEffect(() => { load(); }, []);\n\n  const add = async (e) => {\n    e.preventDefault();\n    await fetch('/api/items', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });\n    setName('');\n    load();\n  };\n\n  return (\n    <main>\n      <h1>Items</h1>\n      {error && <p>{error}</p>}\n      <ul>{items.map((i) => <li key={i.id}>{i.name}</li>)}</ul>\n      <form onSubmit={add}>\n        <input value={name} onChange={(e) => setName(e.target.value)} placeholder=\"New item\" required />\n        <button>Add</button>\n      </form>\n    </main>\n  );\n}\n"}),
        "README.md": "# Full-stack: React + Express\n\nTerminal 1:\n```\ncd server && npm install && npm start\n```\n\nTerminal 2:\n```\ncd client && npm install && npm run dev\n```\n"}},
]

BY_ID = {t["id"]: t for t in TEMPLATES}
