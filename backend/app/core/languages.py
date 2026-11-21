"""Single list of every language the coding workspace knows.

kind:
  run      - executed by the isolated Docker runner (image + command below)
  preview  - shown in the sandboxed browser preview (HTML/CSS)
  edit     - editing, highlighting, versions and review only. These need packages from the
             internet or a long-running server, which the locked-down runner does not allow.
The command runs inside the container with the project mounted read-only at /code and a
writable /tmp. {file} is the path of the file being run.
"""
JS = 'console.log("Hello from WORKCODE");\n'


def L(id, name, ext, monaco, kind="edit", image=None, cmd=None, file=None, template="", timeout=20, user=None, note=None):
    return {"id": id, "name": name, "extensions": ext, "monaco": monaco, "kind": kind, "image": image, "cmd": cmd,
            "file": file or (f"main.{ext[0]}" if ext else "main.txt"), "template": template, "timeout": timeout,
            "user": user, "note": note}


GCC, NODE, JDK = "gcc:13", "node:22-alpine", "eclipse-temurin:21-jdk-alpine"
NEEDS_NET = "Needs npm packages and a running server, so it cannot run in the isolated runner. Edit, save and submit work."

LANGUAGES = [
    # ---- runnable -------------------------------------------------------------------------
    L("python", "Python", ["py"], "python", "run", "python:3.12-alpine", "python3 -u {file}", template='print("Hello from WORKCODE")\n'),
    L("javascript", "JavaScript", ["js", "mjs", "cjs"], "javascript", "run", NODE, "node {file}", template=JS),
    L("node", "Node.js", [], "javascript", "run", NODE, "node {file}", file="index.js", template=JS),
    L("typescript", "TypeScript", ["ts"], "typescript", "run", NODE, "node --experimental-strip-types --no-warnings {file}",
      template='const who: string = "WORKCODE";\nconsole.log(`Hello from ${who}`);\n'),
    L("java", "Java", ["java"], "java", "run", JDK, "java {file}", file="Main.java", timeout=40,
      template='public class Main {\n    public static void main(String[] args) {\n        System.out.println("Hello from WORKCODE");\n    }\n}\n'),
    L("c", "C", ["c"], "c", "run", GCC, "gcc {file} -O1 -o /tmp/a.out -lm && /tmp/a.out",
      template='#include <stdio.h>\n\nint main(void) {\n    printf("Hello from WORKCODE\\n");\n    return 0;\n}\n'),
    L("cpp", "C++", ["cpp", "cc", "cxx"], "cpp", "run", GCC, "g++ -std=c++17 {file} -O1 -o /tmp/a.out && /tmp/a.out", timeout=40,
      template='#include <iostream>\n\nint main() {\n    std::cout << "Hello from WORKCODE" << std::endl;\n    return 0;\n}\n'),
    L("sql", "SQL (SQLite)", ["sql"], "sql", "run", "keinos/sqlite3:latest", "sqlite3 -header -column :memory: < {file}",
      template="CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT);\nINSERT INTO people (name) VALUES ('Asha'), ('Ravi');\nSELECT * FROM people;\n"),
    L("postgresql", "PostgreSQL", ["pgsql", "psql"], "pgsql", "run", "postgres:16-alpine",
      'initdb -D /tmp/pg -A trust >/dev/null && pg_ctl -D /tmp/pg -o "-c listen_addresses= -k /tmp" -w start >/dev/null && '
      "psql -h /tmp -q -v ON_ERROR_STOP=1 -f {file} postgres", timeout=40, user="70:70",
      note="Runs on a temporary empty PostgreSQL server that is deleted after the run.",
      template="CREATE TABLE people (id SERIAL PRIMARY KEY, name TEXT NOT NULL);\nINSERT INTO people (name) VALUES ('Asha'), ('Ravi');\nSELECT * FROM people;\n"),
    L("csharp", "C#", ["cs"], "csharp", "run", "mono:6", "mcs -out:/tmp/a.exe {file} && mono /tmp/a.exe", file="Program.cs", timeout=40,
      template='using System;\n\nclass Program {\n    static void Main() {\n        Console.WriteLine("Hello from WORKCODE");\n    }\n}\n'),
    L("go", "Go", ["go"], "go", "run", "golang:1.22-alpine", "go run {file}", timeout=60,
      template='package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hello from WORKCODE")\n}\n'),
    L("rust", "Rust", ["rs"], "rust", "run", "rust:1-alpine", "rustc -o /tmp/a.out {file} && /tmp/a.out", timeout=60,
      template='fn main() {\n    println!("Hello from WORKCODE");\n}\n'),
    L("php", "PHP", ["php"], "php", "run", "php:8.3-cli-alpine", "php {file}", template='<?php\necho "Hello from WORKCODE\\n";\n'),
    L("ruby", "Ruby", ["rb"], "ruby", "run", "ruby:3.3-alpine", "ruby {file}", template='puts "Hello from WORKCODE"\n'),
    L("perl", "Perl", ["pl"], "perl", "run", "perl:5.38-slim", "perl {file}", template='print "Hello from WORKCODE\\n";\n'),
    L("lua", "Lua", ["lua"], "lua", "run", "nickblah/lua:5.4-alpine", "lua {file}", template='print("Hello from WORKCODE")\n'),
    L("r", "R", ["r"], "r", "run", "r-base:4.4.1", "Rscript {file}", timeout=40, template='cat("Hello from WORKCODE\\n")\n'),
    L("julia", "Julia", ["jl"], "julia", "run", "julia:1.10", "julia {file}", timeout=60, template='println("Hello from WORKCODE")\n'),
    L("kotlin", "Kotlin", ["kt"], "kotlin", "run", "zenika/kotlin:latest",
      "kotlinc {file} -include-runtime -d /tmp/a.jar 2>/dev/null && java -jar /tmp/a.jar", file="Main.kt", timeout=90,
      template='fun main() {\n    println("Hello from WORKCODE")\n}\n'),
    L("swift", "Swift", ["swift"], "swift", "run", "swift:5.10", "swiftc -o /tmp/a.out {file} && /tmp/a.out", timeout=90,
      template='print("Hello from WORKCODE")\n'),
    L("dart", "Dart", ["dart"], "dart", "run", "dart:stable", "dart run {file}", timeout=60,
      template='void main() {\n  print("Hello from WORKCODE");\n}\n'),
    L("bash", "Bash", ["sh", "bash"], "shell", "run", "bash:5", "bash {file}", template='echo "Hello from WORKCODE"\n'),
    L("powershell", "PowerShell", ["ps1"], "powershell", "run", "mcr.microsoft.com/powershell:lts-alpine-3.17",
      "pwsh -NoLogo -NoProfile -File {file}", timeout=40, template='Write-Output "Hello from WORKCODE"\n'),
    L("haskell", "Haskell", ["hs"], "haskell", "run", "haskell:9-slim", "runghc {file}", timeout=60,
      template='main :: IO ()\nmain = putStrLn "Hello from WORKCODE"\n'),
    L("elixir", "Elixir", ["exs", "ex"], "elixir", "run", "elixir:1.16-alpine", "elixir {file}", timeout=40,
      template='IO.puts("Hello from WORKCODE")\n'),
    L("erlang", "Erlang", ["erl"], "erlang", "run", "erlang:26-alpine", "escript {file}", timeout=40,
      template='#!/usr/bin/env escript\nmain(_) ->\n    io:format("Hello from WORKCODE~n").\n'),
    L("ocaml", "OCaml", ["ml"], "ocaml", "run", "ocaml/opam:alpine", "ocaml {file}", timeout=40,
      template='print_endline "Hello from WORKCODE"\n'),
    L("nim", "Nim", ["nim"], "nim", "run", "nimlang/nim:alpine",
      "nim c --verbosity:0 --hints:off --nimcache:/tmp/nim -o:/tmp/a.out {file} && /tmp/a.out", timeout=60,
      template='echo "Hello from WORKCODE"\n'),
    L("lisp", "Common Lisp", ["lisp", "cl"], "lisp", "run", "clfoundation/sbcl:latest", "sbcl --script {file}",
      template='(format t "Hello from WORKCODE~%")\n'),
    L("prolog", "Prolog", ["pro"], "prolog", "run", "swipl:latest", "swipl -q -f {file} -t halt",
      template=':- initialization(main).\nmain :- write(\'Hello from WORKCODE\'), nl.\n'),
    L("fortran", "Fortran", ["f90", "f95", "f"], "fortran", "run", GCC, "gfortran {file} -o /tmp/a.out && /tmp/a.out",
      template='program hello\n  print *, "Hello from WORKCODE"\nend program hello\n'),
    L("matlab", "MATLAB (GNU Octave)", ["m"], "matlab", "run", "gnuoctave/octave:9.2.0", "octave --no-gui --quiet {file}", timeout=40,
      note="Runs with GNU Octave, which is compatible with most MATLAB code.", template='disp("Hello from WORKCODE")\n'),
    L("pascal", "Pascal", ["pas"], "pascal", "run", "freepascal/fpc:latest", "fpc -o/tmp/a.out -FU/tmp {file} >/tmp/fpc.log || cat /tmp/fpc.log; /tmp/a.out",
      template="program Hello;\nbegin\n  writeln('Hello from WORKCODE');\nend.\n"),
    L("d", "D", ["d"], "d", "run", "dlang2/dmd-ubuntu:latest", "dmd -od=/tmp -of=/tmp/a.out {file} && /tmp/a.out", timeout=60,
      template='import std.stdio;\n\nvoid main() {\n    writeln("Hello from WORKCODE");\n}\n'),
    L("crystal", "Crystal", ["cr"], "ruby", "run", "crystallang/crystal:latest", "crystal run {file}", timeout=90,
      template='puts "Hello from WORKCODE"\n'),
    L("groovy", "Groovy", ["groovy"], "groovy", "run", "groovy:4.0-jdk17", "groovy {file}", timeout=60,
      template='println "Hello from WORKCODE"\n'),
    L("racket", "Racket", ["rkt"], "scheme", "run", "racket/racket:8.11-full", "racket {file}", timeout=40,
      template='#lang racket\n(displayln "Hello from WORKCODE")\n'),
    L("scala", "Scala", ["scala", "sc"], "scala", "run", "sbtscala/scala-sbt:eclipse-temurin-21.0.2_13_1.9.9_3.4.0",
      "scala {file}", timeout=90, template='@main def hello(): Unit =\n  println("Hello from WORKCODE")\n'),
    L("awk", "AWK", ["awk"], "plaintext", "run", "bash:5", "awk -f {file}", template='BEGIN { print "Hello from WORKCODE" }\n'),
    # ---- browser preview ------------------------------------------------------------------
    L("html", "HTML", ["html", "htm"], "html", "preview", file="index.html",
      template='<!doctype html>\n<html>\n<head>\n  <meta charset="utf-8">\n  <title>Page</title>\n  <link rel="stylesheet" href="style.css">\n</head>\n<body>\n  <h1>Hello from WORKCODE</h1>\n  <script src="script.js"></script>\n</body>\n</html>\n'),
    L("css", "CSS", ["css"], "css", "preview", file="style.css", template="body {\n  font-family: system-ui, sans-serif;\n}\n"),
    # ---- edit only ------------------------------------------------------------------------
    L("react", "React (JSX)", ["jsx"], "javascript", file="App.jsx", note=NEEDS_NET,
      template="export default function App() {\n  return <h1>Hello from WORKCODE</h1>;\n}\n"),
    L("react_ts", "React (TSX)", ["tsx"], "typescript", file="App.tsx", note=NEEDS_NET,
      template="export default function App() {\n  return <h1>Hello from WORKCODE</h1>;\n}\n"),
    L("express", "Express", [], "javascript", file="server.js", note=NEEDS_NET,
      template="const express = require('express');\nconst app = express();\n\napp.get('/', (req, res) => res.send('Hello from WORKCODE'));\n\napp.listen(3000);\n"),
    L("nextjs", "Next.js", [], "javascript", file="app/page.jsx", note=NEEDS_NET,
      template="export default function Page() {\n  return <h1>Hello from WORKCODE</h1>;\n}\n"),
    L("vue", "Vue", ["vue"], "html", file="App.vue", note=NEEDS_NET, template="<template>\n  <h1>Hello from WORKCODE</h1>\n</template>\n"),
    L("nuxt", "Nuxt", [], "html", file="app.vue", note=NEEDS_NET, template="<template>\n  <h1>Hello from WORKCODE</h1>\n</template>\n"),
    L("svelte", "Svelte", ["svelte"], "html", file="App.svelte", note=NEEDS_NET, template="<h1>Hello from WORKCODE</h1>\n"),
    L("angular", "Angular", [], "typescript", file="app.component.ts", note=NEEDS_NET,
      template="import { Component } from '@angular/core';\n\n@Component({ selector: 'app-root', template: '<h1>Hello from WORKCODE</h1>' })\nexport class AppComponent {}\n"),
    L("scss", "SCSS", ["scss", "sass"], "scss", file="style.scss", template="$brand: #4f8df9;\nbody { color: $brand; }\n"),
    L("less", "Less", ["less"], "less", file="style.less", template="@brand: #4f8df9;\nbody { color: @brand; }\n"),
    L("json", "JSON", ["json"], "json", file="data.json", template='{\n  "name": "workcode"\n}\n'),
    L("yaml", "YAML", ["yml", "yaml"], "yaml", file="config.yml", template="name: workcode\n"),
    L("xml", "XML", ["xml", "svg"], "xml", file="data.xml", template='<?xml version="1.0" encoding="UTF-8"?>\n<root></root>\n'),
    L("markdown", "Markdown", ["md"], "markdown", file="README.md", template="# Title\n"),
    L("toml", "TOML", ["toml"], "ini", file="config.toml", template='name = "workcode"\n'),
    L("ini", "INI", ["ini", "cfg", "env"], "ini", file="config.ini", template="[app]\nname = workcode\n"),
    L("dockerfile", "Dockerfile", ["dockerfile"], "dockerfile", file="Dockerfile", template="FROM alpine:3.20\nCMD [\"echo\", \"Hello from WORKCODE\"]\n"),
    L("graphql", "GraphQL", ["graphql", "gql"], "graphql", file="schema.graphql", template="type Query {\n  hello: String\n}\n"),
    L("mysql", "MySQL", ["mysql"], "mysql", file="main.mysql", note="No MySQL runner. Use SQL (SQLite) or PostgreSQL to run queries.",
      template="SELECT 'Hello from WORKCODE';\n"),
    L("objective_c", "Objective-C", ["mm"], "objective-c", file="main.mm", note="No runner for this language.",
      template='#import <Foundation/Foundation.h>\n\nint main() {\n    NSLog(@"Hello from WORKCODE");\n    return 0;\n}\n'),
    L("fsharp", "F#", ["fs", "fsx"], "fsharp", note="No runner for this language.", template='printfn "Hello from WORKCODE"\n'),
    L("vb", "Visual Basic", ["vb"], "vb", note="No runner for this language.",
      template='Module Program\n    Sub Main()\n        Console.WriteLine("Hello from WORKCODE")\n    End Sub\nEnd Module\n'),
    L("clojure", "Clojure", ["clj"], "clojure", note="No runner for this language.", template='(println "Hello from WORKCODE")\n'),
    L("solidity", "Solidity", ["sol"], "sol", note="No runner for this language.",
      template="// SPDX-License-Identifier: MIT\npragma solidity ^0.8.0;\n\ncontract Hello {\n    string public message = \"Hello from WORKCODE\";\n}\n"),
    L("terraform", "Terraform", ["tf", "hcl"], "hcl", note="No runner for this language.", template='output "hello" {\n  value = "Hello from WORKCODE"\n}\n'),
    L("cobol", "COBOL", ["cob", "cbl"], "plaintext", note="No runner for this language.",
      template="       IDENTIFICATION DIVISION.\n       PROGRAM-ID. HELLO.\n       PROCEDURE DIVISION.\n           DISPLAY 'Hello from WORKCODE'.\n           STOP RUN.\n"),
    L("assembly", "Assembly", ["asm", "s"], "plaintext", note="No runner for this language.", template="; assembly source\n"),
    L("zig", "Zig", ["zig"], "plaintext", note="No runner for this language.",
      template='const std = @import("std");\n\npub fn main() void {\n    std.debug.print("Hello from WORKCODE\\n", .{});\n}\n'),
    L("tcl", "Tcl", ["tcl"], "tcl", note="No runner for this language.", template='puts "Hello from WORKCODE"\n'),
    L("text", "Plain text", ["txt", "log", "csv"], "plaintext", file="notes.txt"),
]

BY_ID = {l["id"]: l for l in LANGUAGES}
BY_EXT = {}
for _l in LANGUAGES:
    for _e in _l["extensions"]:
        BY_EXT.setdefault(_e, _l)


def for_path(path: str):
    name = path.rsplit("/", 1)[-1].lower()
    if name == "dockerfile":
        return BY_ID["dockerfile"]
    return BY_EXT.get(name.rsplit(".", 1)[-1]) if "." in name else None
