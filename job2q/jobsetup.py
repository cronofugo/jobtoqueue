# -*- coding: utf-8 -*-
import sys
from os import listdir, getcwd
from importlib import import_module
from argparse import ArgumentParser
from . import dialogs
from . import messages
from .fileutils import AbsPath, NotAbsolutePath
from .jobparse import run, user, cluster, jobspecs, options
from .utils import Bunch, natsort, p, q, sq, join_arguments, wordseps, boolstrs
from .details import mpilibs

def jobsetup():

    if not jobspecs.scheduler:
        messages.cfgerror('<scheduler> No se especificó el nombre del sistema de colas')
    
    scheduler = import_module('.schedulers.' + jobspecs.scheduler, package='job2q')
    jobformat = Bunch(scheduler.jobformat)
    jobenvars = Bunch(scheduler.jobenvars)
    mpilauncher = scheduler.mpilauncher
    
    if options.ignore_defaults:
        jobspecs.defaults = []
    
    if options.sort:
        run.files.sort(key=natsort)
    elif options.sort_reverse:
        run.files.sort(key=natsort, reverse=True)
    
    if options.wait is None:
        try: options.wait = float(jobspecs.defaults.waitime)
        except AttributeError: options.wait = 0
    
    if options.xdialog:
        try:
            from bulletin import TkDialogs
        except ImportError:
            raise SystemExit()
        else:
            dialogs.yesno = join_arguments(wordseps)(TkDialogs().yesno)
            messages.failure = join_arguments(wordseps)(TkDialogs().message)
            messages.success = join_arguments(wordseps)(TkDialogs().message)

    if not options.outdir and not jobspecs.defaults.outputdir:
        messages.cfgerror('Debe especificar la carpeta de salida por el programa no establece una por defecto')
            
    if not options.scrdir:
        if jobspecs.defaults.scrdir:
            options.scrdir = jobspecs.defaults.scrdir
        else:
            messages.cfgerror('No se especificó el directorio temporal de escritura "scrdir"')
    
    try:
        options.scrdir = AbsPath(options.scrdir).keyexpand(user)
    except NotAbsolutePath:
        messages.cfgerror('La opción "scrdir" debe ser una ruta absoluta')
    
    script.workdir = AbsPath(options.scrdir, jobenvars.jobid)
    script.comments = []
    script.environ = []
    script.command = []

    if not options.queue:
        if jobspecs.defaults.queue:
            options.queue = jobspecs.defaults.queue
        else:
            messages.cfgerror('<default><queue> No se especificó la cola por defecto')
    
    if not jobspecs.progname:
        messages.cfgerror('<title> No se especificó el nombre del programa')
    
    if not jobspecs.progkey:
        messages.cfgerror('<title> No se especificó la clave del programa')
    
    if 'mpilauncher' in jobspecs:
        try: jobspecs.mpilauncher = boolstrs[jobspecs.mpilauncher]
        except KeyError:
            messages.cfgerror('<mpilauncher> El texto de este tag debe ser "True" o "False"')
    
    if not jobspecs.filekeys:
        messages.cfgerror('<filekeys> La lista de archivos del programa no existe o está vacía')
    
    if jobspecs.inputfiles:
        for item in jobspecs.inputfiles:
            for key in item.split('|'):
                if not key in jobspecs.filekeys:
                    messages.cfgerror('<inputfiles><e>{0}</e> El nombre de este archivo de entrada no fue definido'.format(key))
    else:
        messages.cfgerror('<inputfiles> La lista de archivos de entrada no existe o está vacía')
    
    if jobspecs.outputfiles:
        for item in jobspecs.outputfiles:
            for key in item.split('|'):
                if not key in jobspecs.filekeys:
                    messages.cfgerror('<otputfiles><e>{0}</e> El nombre de este archivo de salida no fue definido'.format(key))
    else:
        messages.cfgerror('<outputfiles> La lista de archivos de salida no existe o está vacía')
    
    #TODO: MPI support for Slurm
    if jobspecs.parallelib:
        if jobspecs.parallelib.lower() == 'none':
            script.comments.append(jobformat.nhost(options.nhost))
        elif jobspecs.parallelib.lower() == 'openmp':
            script.comments.append(jobformat.ncore(options.ncore))
            script.comments.append(jobformat.nhost(options.nhost))
            script.command.append('OMP_NUM_THREADS=' + str(options.ncore))
        elif jobspecs.parallelib.lower() in mpilibs:
            if not 'mpilauncher' in jobspecs:
                messages.cfgerror('<mpilauncher> No se especificó si el programa es lanzado por mpirun')
            script.comments.append(jobformat.ncore(options.ncore))
            script.comments.append(jobformat.nhost(options.nhost))
            if jobspecs.mpilauncher:
                script.command.append(mpilauncher[jobspecs.parallelib])
        else:
            messages.cfgerror('El tipo de paralelización ' + jobspecs.parallelib + ' no está soportado')
    else:
        messages.cfgerror('<parallelib> No se especificó el tipo de paralelización del programa')
    
    if jobspecs.versions:
        if not options.version:
            if 'version' in jobspecs.defaults:
                if jobspecs.defaults.version in jobspecs.versions:
                    options.version = jobspecs.defaults.version
                else:
                    messages.opterror('La versión establecida por default es inválida')
            else:
                options.version = dialogs.chooseone('Seleccione una versión', choices=sorted(list(jobspecs.versions), key=natsort))
                if not options.version in jobspecs.versions:
                    messages.opterror('La versión seleccionada es inválida')
    else:
        messages.cfgerror('<versions> La lista de versiones no existe o está vacía')

    versionspec = jobspecs.versions[options.version]
    
    if not versionspec.executable:
        messages.cfgerror('No se especificó el ejecutable de la versión', options.version)
    
    script.environ.extend(jobspecs.onscript)

    for envar, path in jobspecs.export.items() | versionspec.export.items():
        script.environ.append('export {}={}'.format(envar, AbsPath(path.format(workdir=script.workdir)).keyexpand(user)))
    
    for path in jobspecs.source + versionspec.source:
        script.environ.append('source {}'.format(AbsPath(path).keyexpand(user)))
    
    for module in jobspecs.load + versionspec.load:
        script.environ.append('module load {}'.format(module))
    
    try:
        script.command.append(AbsPath(versionspec.executable).keyexpand(user))
    except NotAbsolutePath:
        script.command.append(versionspec.executable)
    
    script.comments.append(jobformat.label(jobspecs.progname))
    script.comments.append(jobformat.queue(options.queue))
    script.comments.append(jobformat.output(AbsPath(jobspecs.logdir).keyexpand(user)))
    script.comments.append(jobformat.error(AbsPath(jobspecs.logdir).keyexpand(user)))
    
    if options.node:
        script.comments.append(jobformat.hosts(options.node))
    
    script.environ.append("shopt -s nullglob extglob")
    script.environ.append("head=" + cluster.head)
    script.environ.extend('='.join(i) for i in jobenvars.items())
    script.environ.append("freeram=$(free -m | tail -n+3 | head -1 | awk '{print $4}')")
    script.environ.append("totalram=$(free -m | tail -n+2 | head -1 | awk '{print $2}')")
    script.environ.append("jobram=$(($ncore*$totalram/$(nproc --all)))")
    
    for var in jobspecs.filevars:
        script.environ.append(var + '=' + sq(jobspecs.filekeys[jobspecs.filevars[var]]))
    
    for key in jobspecs.optionargs:
        if not jobspecs.optionargs[key] in jobspecs.filekeys:
            messages.cfgerror('<optionargs><e>{0}</e> El nombre de este archivo de entrada/salida no fue definido'.format(key))
        script.command.append('-{key} {val}'.format(key=key, val=jobspecs.filekeys[jobspecs.optionargs[key]]))
    
    for item in jobspecs.positionargs:
        for key in item.split('|'):
            if not key in jobspecs.filekeys:
                messages.cfgerror('<positionargs><e>{0}</e> El nombre de este archivo de entrada/salida no fue definido'.format(key))
        script.command.append('@' + p('|'.join(jobspecs.filekeys[i] for i in item.split('|'))))
    
    if 'stdin' in jobspecs:
        try: script.command.append('0<' + ' ' + jobspecs.filekeys[jobspecs.stdin])
        except KeyError: messages.cfgerror('El nombre de archivo "' + jobspecs.stdin + '" en el tag <stdin> no fue definido.')
    if 'stdoutput' in jobspecs:
        try: script.command.append('1>' + ' ' + jobspecs.filekeys[jobspecs.stdoutput])
        except KeyError: messages.cfgerror('El nombre de archivo "' + jobspecs.stdoutput + '" en el tag <stdoutput> no fue definido.')
    if 'stderror' in jobspecs:
        try: script.command.append('2>' + ' ' + jobspecs.filekeys[jobspecs.stderror])
        except KeyError: messages.cfgerror('El nombre de archivo "' + jobspecs.stderror + '" en el tag <error> no fue definido.')
    
    script.chdir = 'cd "{}"'.format
    script.runathead = 'ssh $head "{}"'.format
    if jobspecs.hostcopy == 'local':
        script.mkdir = 'mkdir -p -m 700 "{}"'.format
        script.rmdir = 'rm -rf "{}"'.format
        script.fetch = 'cp "{}" "{}"'.format
        script.fetch = 'cp "{}" "{}"'.format
        script.fetchdir = 'cp -r "{}/." "{}"'.format
        script.remit = 'cp "{}" "{}"'.format
    elif jobspecs.hostcopy == 'remote':
        script.mkdir = 'for host in ${{hosts[*]}}; do ssh $host mkdir -p -m 700 "\'{0}\'"; done'.format
        script.rmdir = 'for host in ${{hosts[*]}}; do ssh $host rm -rf "\'{0}\'"; done'.format
        script.fetch = 'for host in ${{hosts[*]}}; do scp $head:"\'{0}\'" $host:"\'{1}\'"; done'.format
        #script.fetchdir = 'for host in ${{hosts[*]}}; do scp $head:"\'{0}\/.'" . $host:"\'{1}/\'"; done'.format
        script.fetchdir = 'for host in ${{hosts[*]}}; do ssh $head tar -cf- -C "\'{0}\'" . | ssh $host tar -xf- -C "\'{1}/\'"; done'.format
        script.remit = 'scp "{}" $head:"\'{}\'"'.format
    else:
        messages.cfgerror('El método de copia', q(jobspecs.hostcopy), 'no es válido')
    
    for parkey in jobspecs.parameters:
        if options[parkey + '_path']:
            try:
                rootpath = AbsPath(options[parkey + '_path'])
            except NotAbsolutePath:
                rootpath = AbsPath(getcwd(), options[parkey + '_path'])
        elif parkey in jobspecs.defaults.parameters:
            if options[parkey + '_set']:
                optparts = options[parkey + '_set'].split(':')
            else:
                optparts = []
            try:
                abspath = AbsPath(jobspecs.defaults.parameters[parkey])
            except NotAbsolutePath:
                abspath = AbsPath(getcwd(), jobspecs.defaults.parameters[parkey])
            rootpath = AbsPath('/')
            for part, key, default in abspath.setkeys(user).splitkeys():
                if key is None:
                    rootpath = rootpath.joinpath(part)
                else:
                    if optparts:
                        rootpath = rootpath.joinpath(part, optparts.pop(0))
                    elif default:
                        rootpath = rootpath.joinpath(part, default)
                    else:
                        rootpath = rootpath.joinpath(part)
                        try:
                            diritems = rootpath.listdir()
                        except FileNotFoundError:
                            messages.cfgerror('El directorio', self, 'no existe')
                        except NotADirectoryError:
                            messages.cfgerror('La ruta', self, 'no es un directorio')
                        if not diritems:
                            messages.cfgerror('El directorio', self, 'está vacío')
                        diritems.sort(key=natsort)
                        choice = dialogs.chooseone('Seleccione un conjunto de parámetros', p(key), choices=diritems)
                        rootpath = rootpath.joinpath(choice)
        else:
            messages.opterror('Debe indicar la ruta al directorio de parámetros', p(parkey))
        if rootpath.exists():
            parameters.append(rootpath)
        else:
            messages.opterror('La ruta', rootpath, 'no existe', p(parkey))
    
script = Bunch()
parameters = []

