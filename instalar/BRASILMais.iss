; Instalador do BRASIL+ (Inno Setup 6). Gerado pelo GitHub (.github/workflows/instalador.yml):
;   iscc /DVersao=1.0.0 instalar\BRASILMais.iss      ->  saida\BRASILMais-Setup.exe
; Instala so para o usuario (sem pedir administrador). Os DADOS ficam em C:\Users\<voce>\BRASILMais e nunca sao tocados.
#ifndef Versao
  #define Versao "0.0.0"
#endif

[Setup]
AppId={{6F1D3B5A-8E24-4C7A-9B0D-2A5C7E91F4D3}
AppName=BRASIL+
AppVersion={#Versao}
AppPublisher=BRASIL+
DefaultDirName={localappdata}\Programs\BRASILMais
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\saida
OutputBaseFilename=BRASILMais-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=BRASILMaisMutex
CloseApplications=yes
RestartApplications=no
UninstallDisplayName=BRASIL+
UninstallDisplayIcon={app}\BRASILMais.exe

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "startup"; Description: "Abrir o BRASIL+ sozinho quando eu ligar o computador"; GroupDescription: "Opcoes:"
Name: "desktopicon"; Description: "Criar um atalho na area de trabalho"; GroupDescription: "Opcoes:"

[Files]
Source: "..\build-exe\dist\BRASILMais\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\site\*"; DestDir: "{userprofile}\BRASILMais\site"; Flags: recursesubdirs onlyifdoesntexist uninsneveruninstall skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\BRASIL+"; Filename: "{app}\BRASILMais.exe"
Name: "{autodesktop}\BRASIL+"; Filename: "{app}\BRASILMais.exe"; Tasks: desktopicon
Name: "{userstartup}\BRASIL+"; Filename: "{app}\BRASILMais.exe"; Parameters: "--sem-navegador"; Tasks: startup

[Run]
Filename: "{app}\BRASILMais.exe"; Description: "Abrir o BRASIL+ agora"; Flags: nowait postinstall
