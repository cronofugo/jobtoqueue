# -*- coding: utf-8 -*-
import os
import sys
from time import sleep
from argparse import ArgumentParser, Action, SUPPRESS
from subprocess import check_output, CalledProcessError, STDOUT
from . import messages
from .readspec import readspec
from .utils import Bunch, DefaultStr, _, o, p, q, printtree, getformatkeys
from .fileutils import AbsPath, NotAbsolutePath, formpath, findbranches
from .shared import ArgList, names, paths, environ, hostspecs, jobspecs, options, remoteargs
from .submit import initialize, submit 

class LsOptions(Action):
    def __init__(self, **kwargs):
        super().__init__(nargs=0, **kwargs)
    def __call__(self, parser, namespace, values, option_string=None):
        if jobspecs.versions:
            print(_('Versiones del programa:'))
            printtree([DefaultStr(i) if i == jobspecs.defaults.version else str(i) for i in jobspecs.versions], level=1)
        for path in jobspecs.defaults.parameterpaths:
            dirtree = {}
            partlist = AbsPath(path).setkeys(names).parts()
            findbranches(AbsPath(next(partlist)), partlist, jobspecs.defaults.parameters, dirtree)
            if dirtree:
               print(_('Parámetros en $path:').format(path=path.format(**{i: '*' for i in getformatkeys(path)})))
               printtree(dirtree, level=1)
        if jobspecs.interpolationkeywords:
            print(_('Variables de interpolación:'))
            printtree(jobspecs.interpolationkeywords, level=1)
        raise SystemExit()

class SetCwd(Action):
    def __init__(self, **kwargs):
        super().__init__(nargs=1, **kwargs)
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, AbsPath(values[0], cwd=os.getcwd()))

class AppendKey(Action):
    def __init__(self, **kwargs):
        super().__init__(nargs=1, **kwargs)
    def __call__(self, parser, namespace, values, option_string=None):
        getattr(namespace, self.const).update({self.dest:values[0]})

try:

    try:
        specdir = os.environ['SPECDIR']
    except KeyError:
        messages.error('No se definió la variable de entorno SPECDIR')
    
    parser = ArgumentParser(add_help=False)
    parser.add_argument('program', metavar='PROGNAME', help='Nombre estandarizado del programa.')
    parsedargs, remainingargs = parser.parse_known_args()
    names.command = parsedargs.program
    
    hostspecs.merge(readspec(formpath(specdir, names.command, 'clusterspecs.json')))
    hostspecs.merge(readspec(formpath(specdir, names.command, 'queuespecs.json')))

    jobspecs.merge(readspec(formpath(specdir, names.command, 'packagespecs.json')))
    jobspecs.merge(readspec(formpath(specdir, names.command, 'packageconf.json')))
    
    userspecdir = formpath(paths.home, '.jobspecs', names.command + '.json')
    
    if os.path.isfile(userspecdir):
        jobspecs.merge(readspec(userspecdir))
    
    try: names.cluster = hostspecs.clustername
    except AttributeError:
        messages.error('No se definió el nombre del clúster', spec='clustername')

    try: names.head = hostspecs.headname
    except AttributeError:
        messages.error('No se definió el nombre del nodo maestro', spec='clustername')

    parser = ArgumentParser(prog=names.command, add_help=False, description='Envía trabajos de {} a la cola de ejecución.'.format(jobspecs.packagename))

    group1 = parser.add_argument_group('Argumentos')
    group1.add_argument('files', nargs='*', metavar='FILE', help='Rutas de los archivos de entrada.')
    group1.name = 'arguments'
    group1.remote = False

#    group1 = parser.add_argument_group('Ejecución remota')

    group2 = parser.add_argument_group('Opciones comunes')
    group2.name = 'common'
    group2.remote = True
    group2.add_argument('-h', '--help', action='help', help='Mostrar este mensaje de ayuda y salir.')
    group2.add_argument('-d', '--defaults', action='store_true', help='Ignorar las opciones predeterminadas y preguntar.')
    group2.add_argument('-f', '--filter', metavar='REGEX', default=SUPPRESS, help='Enviar únicamente los trabajos que coinciden con la expresión regular.')
    group2.add_argument('-j', '--jobname', action='store_true', help='Interpretar los argumentos como nombres de trabajos en vez de rutas de archivo.')
    group2.add_argument('-l', '--list', action=LsOptions, default=SUPPRESS, help='Mostrar las opciones disponibles y salir.')
    group2.add_argument('-n', '--nproc', type=int, metavar='#PROCS', default=1, help='Número de núcleos de procesador requeridos.')
    group2.add_argument('-o', '--outdir', metavar='PATH', default=SUPPRESS, help='Escribir los archivos de salida en el directorio PATH.')
    group2.add_argument('-q', '--queue', metavar='QUEUENAME', default=SUPPRESS, help='Nombre de la cola requerida.')
    group2.add_argument('-s', '--sort', metavar='ORDER', default=SUPPRESS, help='Ordenar los argumentos de acuerdo al orden ORDER.')
    group2.add_argument('-v', '--version', metavar='PROGVERSION', default=SUPPRESS, help='Versión del ejecutable.')
    group2.add_argument('-w', '--wait', type=float, metavar='TIME', default=SUPPRESS, help='Tiempo de pausa (en segundos) después de cada ejecución.')
    group2.add_argument('--cwd', action=SetCwd, metavar='PATH', default=os.getcwd(), help='Establecer PATH como el directorio actual para rutas relativas.')
    group2.add_argument('--parlib', metavar='PATH', action='append', default=[], help='Agregar la biblioteca de parámetros PATH.')
    group2.add_argument('--scratch', metavar='PATH', default=SUPPRESS, help='Escribir los archivos temporales en el directorio PATH.')
    group2.add_argument('--delete', action='store_true', help='Borrar los archivos de entrada después de enviar el trabajo.')
    group2.add_argument('--prefix', metavar='PREFIX', default=SUPPRESS, help='Agregar el prefijo PREFIX al nombre del trabajo.')
    group2.add_argument('--suffix', metavar='SUFFIX', default=SUPPRESS, help='Agregar el sufijo SUFFIX al nombre del trabajo.')
    group2.add_argument('--debug', action='store_true', help='Procesar los archivos de entrada sin enviar el trabajo.')
    hostgroup = group2.add_mutually_exclusive_group()
    hostgroup.add_argument('-N', '--nodes', type=int, metavar='#NODES', default=SUPPRESS, help='Número de nodos de ejecución requeridos.')
    hostgroup.add_argument('--nodelist', metavar='NODE', default=SUPPRESS, help='Solicitar nodos específicos de ejecución.')
    yngroup = group2.add_mutually_exclusive_group()
    yngroup.add_argument('--yes', '--si', action='store_true', help='Responder "si" a todas las preguntas.')
    yngroup.add_argument('--no', action='store_true', help='Responder "no" a todas las preguntas.')
#    group2.add_argument('-X', '--xdialog', action='store_true', help='Habilitar el modo gráfico para los mensajes y diálogos.')

    group3 = parser.add_argument_group('Opciones remotas')
    group3.name = 'remote'
    group3.remote = False 
    group3.add_argument('-H', '--host', metavar='HOSTNAME', help='Procesar el trabajo en el host HOSTNAME.')

    group4 = parser.add_argument_group('Conjuntos de parámetros')
    group4.name = 'parameters'
    group4.remote = True
    for key in jobspecs.parameters:
        group4.add_argument(o(key), metavar='PARAMETERSET', default=SUPPRESS, help='Nombre del conjunto de parámetros.')

    group5 = parser.add_argument_group('Archivos opcionales')
    group5.name = 'optionalfiles'
    group5.remote = False
    for key, value in jobspecs.fileoptions.items():
        group5.add_argument(o(key), metavar='FILEPATH', default=SUPPRESS, help='Ruta al archivo {}.'.format(value))

    group6 = parser.add_argument_group('Opciones de interpolación')
    group6.name = 'interpolation'
    group6.remote = False
    group6.add_argument('-i', '--interpolate', action='store_true', help='Interpolar los archivos de entrada.')
    group6.add_argument('-x', '--var', dest='vars', metavar='VALUE', action='append', default=[], help='Variables posicionales de interpolación.')
    molgroup = group6.add_mutually_exclusive_group()
    molgroup.add_argument('-m', '--mol', metavar='MOLFILE', action='append', default=[], help='Agregar el paso final del archivo MOLFILE a las coordenadas de interpolación.')
    molgroup.add_argument('-M', '--trjmol', metavar='MOLFILE', default=SUPPRESS, help='Usar todos los pasos del archivo MOLFILE como coordenadas de interpolación.')

    group7 = parser.add_argument_group('Opciones de interpolación')
    group7.name = 'interpolationdict'
    group7.remote = False
    for key in jobspecs.interpolationkeywords:
        group7.add_argument(o(key), metavar=key.upper(), default=SUPPRESS, help='Variable de interpolación.')

    parsedargs = parser.parse_args(remainingargs)
#    print(parsedargs)

    for group in parser._action_groups:
        group_dict = {a.dest:getattr(parsedargs, a.dest) for a in group._group_actions if a.dest in parsedargs}
        if hasattr(group, 'name'):
            options[group.name] = Bunch(**group_dict)
        if hasattr(group, 'remote') and group.remote:
            remoteargs.gather(Bunch(**group_dict))

#    print(options)
#    print(remoteargs)

    if parsedargs.files:
        arglist = ArgList(parsedargs.files)
    else:
        messages.error('Debe especificar al menos un archivo de entrada')

    for key in options.optionalfiles:
        options.optionalfiles[key] = AbsPath(options.optionalfiles[key], cwd=options.common.cwd)
        if not options.optionalfiles[key].isfile():
            messages.error('El archivo de entrada', options.optionalfiles[key], 'no existe', option=o(key))

    try:
        environ.TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
    except KeyError:
        pass

    if options.remote.host:

        try:
            output = check_output(['ssh', options.remote.host, 'echo $JOB2Q_CMD:$JOB2Q_ROOT'], stderr=STDOUT)
        except CalledProcessError as exc:
            messages.error(exc.output.decode(sys.stdout.encoding).strip())
        options.remote.cmd, options.remote.root = output.decode(sys.stdout.encoding).strip().split(':')
        if not options.remote.root or not options.remote.cmd:
            messages.error('El servidor remoto no acepta trabajos de otro servidor')

#        #TODO: Consider include trjmol and mol paths in optionalfiles
#        if 'trjmol' in options.interpolation:
#            filelist.append(formpath(paths.home, '.', os.path.relpath(options.interpolation.trjmol, paths.home)))
#        for path in options.interpolation.mol:
#            filelist.append(formpath(paths.home, '.', os.path.relpath(path, paths.home)))
#        #TODO: (done?) Make default empty dict for optionalfiles so no test is needed
#        for path in options.optionalfiles.values():
#            filelist.append(formpath(paths.home, '.', os.path.relpath(path, paths.home)))

    initialize()

    try:
        basedir, basename = next(arglist)
    except StopIteration:
        sys.exit()

    submit(basedir, basename)
    for basedir, basename in arglist:
        sleep(options.common.wait)
        submit(basedir, basename)
    
except KeyboardInterrupt:
    messages.error('Interrumpido por el usuario')

